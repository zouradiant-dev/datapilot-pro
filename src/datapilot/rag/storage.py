"""Fixed SQL infrastructure; neither ingest nor retrieval accepts arbitrary SQL."""

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.rag.contracts import (
    ChunkCitation,
    Chunker,
    ChunkSpan,
    CorpusPin,
    IndexManifest,
    Limits,
    RagScope,
    Target,
)
from datapilot.rag.models import validate_vectors
from datapilot.rag.parsing import decode, parse_sources


def sql(conn, statement, **params):
    return conn.execute(sa.text(statement), params)


class Connection:
    def __init__(self, url: str, role: str, *, timeout=2):
        parsed = make_url(url)
        if (
            parsed.username != role
            or parsed.drivername != "postgresql+psycopg"
            or not 0 < timeout <= 30
        ):
            raise AgentFailure("ROLE_UNSAFE", "Use the designated isolated RAG role")
        self.engine = sa.create_engine(
            url, hide_parameters=True, connect_args={"connect_timeout": 5}
        )
        self.timeout = timeout
        with self.engine.connect() as conn:
            flags = conn.exec_driver_sql(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR "
                "rolreplication OR rolbypassrls OR rolinherit FROM pg_roles "
                "WHERE rolname=current_user"
            ).scalar_one()
            member = conn.exec_driver_sql(
                "SELECT count(*) FROM pg_auth_members WHERE "
                "member=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
            ).scalar_one()
            ddl = conn.exec_driver_sql(
                "SELECT has_schema_privilege(current_user,'rag','CREATE')"
            ).scalar_one()
            if (
                flags
                or member
                or ddl
                or int(conn.exec_driver_sql("SHOW server_version_num").scalar_one()) // 10000 != 17
            ):
                raise AgentFailure(
                    "ROLE_UNSAFE", "RAG identity must be restricted on PostgreSQL 17"
                )

    def close(self):
        self.engine.dispose()

    @contextmanager
    def read(self):
        try:
            with self.engine.connect() as conn, conn.begin():
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                sql(
                    conn,
                    "SELECT set_config('statement_timeout',:timeout,true)",
                    timeout=str(max(1, int(self.timeout * 1000))),
                )
                conn.exec_driver_sql("SET LOCAL lock_timeout='500ms'")
                conn.exec_driver_sql("SET LOCAL search_path=pg_catalog,public")
                yield conn
        except sa.exc.DBAPIError as exc:
            timeout = getattr(exc.orig, "sqlstate", None) == "57014"
            raise AgentFailure(
                "RAG_QUERY_TIMEOUT" if timeout else "RAG_DATABASE_ERROR",
                "Read-only retrieval transaction timed out"
                if timeout
                else "Retrieval database failed",
                retryable=timeout,
            ) from None


class IngestionService(Connection):
    def __init__(self, url, embedding, *, limits=None):
        super().__init__(url, "datapilot_rag_ingest")
        self.embedding, self.limits = embedding, limits or Limits()

    def ingest(
        self, target: Target, paths: list[Path], *, scope: RagScope, reviewed=False, chunker=None
    ):
        target = Target.model_validate_json(target.model_dump_json())
        scope = RagScope.model_validate_json(scope.model_dump_json())
        if reviewed is not True or not scope.permits(target):
            raise AgentFailure(
                "DOCUMENT_NOT_AUTHORIZED", "Host review and exact target grant required"
            )
        chunker = chunker or Chunker()
        parsed = parse_sources(paths, target.corpus_id, chunker, self.limits)
        manifest = IndexManifest(
            target=target,
            model=self.embedding.spec,
            chunker=chunker,
            sources=sorted((p.info for p in parsed), key=lambda s: s.source_id),
        )
        index_version = digest(manifest)
        with self.read() as conn:
            existing = sql(
                conn,
                "SELECT manifest FROM rag.indexes WHERE corpus_id=:c AND index_version=:v",
                c=target.corpus_id,
                v=index_version,
            ).scalar_one_or_none()
        if existing is not None:
            if digest(existing) != index_version:
                raise AgentFailure("DOCUMENT_CORRUPT", "Existing index manifest changed")
            return manifest, index_version, True, None
        fragments = [p.text[s.start : s.end] for p in parsed for s in p.info.chunks]
        vectors, usage = self.embedding.encode(fragments)
        vectors = validate_vectors(vectors, len(fragments))
        try:
            with self.engine.begin() as conn:
                conn.exec_driver_sql("SET LOCAL statement_timeout='10s'")
                conn.exec_driver_sql("SET LOCAL lock_timeout='2s'")
                sql(
                    conn,
                    "SELECT pg_advisory_xact_lock(hashtextextended(:c, 7511))",
                    c=target.corpus_id,
                )
                sql(
                    conn,
                    "INSERT INTO rag.corpora(corpus_id,target) VALUES (:c,CAST(:t AS jsonb)) "
                    "ON CONFLICT DO NOTHING",
                    c=target.corpus_id,
                    t=target.model_dump_json(),
                )
                original = sql(
                    conn, "SELECT target FROM rag.corpora WHERE corpus_id=:c", c=target.corpus_id
                ).scalar_one()
                if digest(original) != digest(target):
                    raise AgentFailure(
                        "DOCUMENT_NOT_AUTHORIZED", "Corpus target/owner is immutable"
                    )
                for p in parsed:
                    info = p.info.model_dump(mode="json", exclude={"chunks"})
                    sql(
                        conn,
                        "INSERT INTO rag.sources(corpus_id,document_id,info,raw) VALUES "
                        "(:c,:id,CAST(:info AS jsonb),:raw) ON CONFLICT DO NOTHING",
                        c=target.corpus_id,
                        id=p.info.document_id,
                        info=json.dumps(info),
                        raw=p.raw,
                    )
                    stored = sql(
                        conn,
                        "SELECT info,raw FROM rag.sources WHERE corpus_id=:c AND document_id=:id",
                        c=target.corpus_id,
                        id=p.info.document_id,
                    ).one()
                    if stored.info != info or bytes(stored.raw) != p.raw:
                        raise AgentFailure(
                            "DOCUMENT_CORRUPT", "Immutable source snapshot conflicts"
                        )
                sql(
                    conn,
                    "INSERT INTO rag.indexes(corpus_id,index_version,manifest) VALUES "
                    "(:c,:v,CAST(:m AS jsonb)) ON CONFLICT DO NOTHING",
                    c=target.corpus_id,
                    v=index_version,
                    m=manifest.model_dump_json(),
                )
                rows = []
                i = 0
                for p in parsed:
                    for span in p.info.chunks:
                        vector = vectors[i]
                        rows.append(
                            {
                                "c": target.corpus_id,
                                "v": index_version,
                                "id": span.chunk_id,
                                "doc": p.info.document_id,
                                "span": span.model_dump_json(),
                                "text": p.text[span.start : span.end],
                                "vector": json.dumps(vector.tolist()),
                                "hash": hashlib.sha256(vector.astype("<f4").tobytes()).hexdigest(),
                            }
                        )
                        i += 1
                if rows:
                    conn.execute(
                        sa.text(
                            "INSERT INTO rag.chunks "
                            "(corpus_id,index_version,chunk_id,document_id,span,text,embedding,embedding_sha256)"
                            " VALUES (:c,:v,:id,:doc,CAST(:span AS jsonb),:text,"
                            "CAST(:vector AS public.vector),:hash) "
                            "ON CONFLICT DO NOTHING"
                        ),
                        rows,
                    )
        except sa.exc.SQLAlchemyError:
            raise AgentFailure(
                "RAG_INGEST_ERROR", "Atomic document ingestion rolled back"
            ) from None
        return manifest, index_version, False, usage


class Repository(Connection):
    def __init__(self, url, scope: RagScope, *, timeout=2):
        super().__init__(url, "datapilot_rag_reader", timeout=timeout)
        self.scope = RagScope.model_validate_json(scope.model_dump_json())

    def manifests(self):
        values = {}
        with self.read() as conn:
            for pin in self.scope.corpora:
                row = sql(
                    conn,
                    "SELECT manifest FROM rag.indexes WHERE corpus_id=:c AND index_version=:v",
                    c=pin.corpus_id,
                    v=pin.index_version,
                ).scalar_one_or_none()
                if row is None or digest(row) != pin.index_version:
                    raise AgentFailure(
                        "DOCUMENT_NOT_AUTHORIZED", "Pinned index is missing or changed"
                    )
                manifest = IndexManifest.model_validate_json(json.dumps(row))
                if (
                    manifest.target.corpus_id != pin.corpus_id
                    or not self.scope.permits(manifest.target)
                    or set(pin.document_ids) != {s.document_id for s in manifest.sources}
                ):
                    raise AgentFailure(
                        "DOCUMENT_NOT_AUTHORIZED", "Document/dataset scope was not delegated"
                    )
                for source in manifest.sources:
                    raw = sql(
                        conn,
                        "SELECT raw FROM rag.sources WHERE corpus_id=:c AND document_id=:d",
                        c=pin.corpus_id,
                        d=source.document_id,
                    ).scalar_one_or_none()
                    if raw is None or hashlib.sha256(bytes(raw)).hexdigest() != source.version:
                        raise AgentFailure(
                            "DOCUMENT_CORRUPT", "Original source snapshot hash differs"
                        )
                    text = decode(bytes(raw))
                    if hashlib.sha256(text.encode()).hexdigest() != source.text_sha256:
                        raise AgentFailure("DOCUMENT_CORRUPT", "Source decoding hash differs")
                    for span in source.chunks:
                        if (
                            span.end > len(text)
                            or hashlib.sha256(text[span.start : span.end].encode()).hexdigest()
                            != span.sha256
                            or span.line_start != 1 + text.count("\n", 0, span.start)
                            or span.line_end != 1 + text.count("\n", 0, span.end - 1)
                        ):
                            raise AgentFailure(
                                "DOCUMENT_CORRUPT", "Source span/hash cannot be reproduced"
                            )
                values[pin.corpus_id] = manifest
        return values

    def search(self, query: str, top_k: int, embedding):
        from datapilot.orchestration.contracts import Document, SearchResult

        if (
            type(top_k) is not int
            or not 1 <= top_k <= 5
            or not isinstance(query, str)
            or not 1 <= len(query.strip()) <= 512
        ):
            raise AgentFailure("INPUT_INVALID", "Bounded nonempty query and top_k 1..5 required")
        manifests = self.manifests()
        if not any(p.document_ids for p in self.scope.corpora):
            return SearchResult(
                documents=[],
                requested_top_k=top_k,
                retriever_version="pg-cosine-exact-1",
                unavailable_reason="no_authorized_documents",
            )
        if any(m.model != embedding.spec for m in manifests.values()):
            raise AgentFailure(
                "EMBEDDING_VERSION", "Query embedding must match the immutable index"
            )
        vectors, usage = embedding.encode([query], query=True)
        vector = validate_vectors(vectors, 1)[0].tolist()
        documents = []
        with self.read() as conn:
            for pin in self.scope.corpora:
                if not pin.document_ids:
                    continue
                rows = (
                    sql(
                        conn,
                        "SELECT chunk_id,document_id,span,text,embedding::text AS vector,"
                        "embedding_sha256,1-(embedding OPERATOR(public.<=>) "
                        "CAST(:vector AS public.vector)) AS score "
                        "FROM rag.chunks WHERE corpus_id=:c AND index_version=:v "
                        "AND document_id=ANY(CAST(:docs AS text[])) "
                        "ORDER BY embedding OPERATOR(public.<=>) CAST(:vector AS public.vector),"
                        "chunk_id LIMIT :k",
                        c=pin.corpus_id,
                        v=pin.index_version,
                        docs=pin.document_ids,
                        vector=json.dumps(vector),
                        k=top_k,
                    )
                    .mappings()
                    .all()
                )
                manifest = manifests[pin.corpus_id]
                for row in rows:
                    stored_vector = validate_vectors([json.loads(row["vector"])], 1)[0]
                    if (
                        hashlib.sha256(stored_vector.astype("<f4").tobytes()).hexdigest()
                        != row["embedding_sha256"]
                    ):
                        raise AgentFailure("DOCUMENT_CORRUPT", "Stored embedding hash differs")
                    source = next(
                        s for s in manifest.sources if s.document_id == row["document_id"]
                    )
                    span = next((s for s in source.chunks if s.chunk_id == row["chunk_id"]), None)
                    if (
                        span is None
                        or row["span"] != span.model_dump()
                        or hashlib.sha256(row["text"].encode()).hexdigest() != span.sha256
                    ):
                        raise AgentFailure(
                            "DOCUMENT_CORRUPT", "Retrieved chunk differs from manifest/source"
                        )
                    score = max(-1.0, min(1.0, float(row["score"])))
                    if score < self.scope.min_score:
                        continue
                    citation = ChunkCitation(
                        **span.model_dump(),
                        corpus_id=pin.corpus_id,
                        index_version=pin.index_version,
                        source_id=source.source_id,
                        document_id=source.document_id,
                        version=source.version,
                        source_sha256=source.version,
                        model_revision=manifest.model.revision,
                        chunker_sha256=digest(manifest.chunker),
                        score=score,
                    )
                    documents.append(
                        Document(
                            document_id=span.chunk_id,
                            source=source.name,
                            version=source.version,
                            text=row["text"],
                            sha256=span.sha256,
                            citation=citation,
                        )
                    )
        documents.sort(key=lambda d: (-d.citation.score, d.document_id))
        return SearchResult(
            documents=documents[:top_k],
            fixture=embedding.spec.fixture,
            requested_top_k=top_k,
            retriever_version="pg-cosine-exact-1",
            embedding_usage=usage,
            unavailable_reason=None if documents else "no_matches",
        )


def make_pin(manifest: IndexManifest, index_version: str) -> CorpusPin:
    return CorpusPin(
        corpus_id=manifest.target.corpus_id,
        index_version=index_version,
        document_ids=[s.document_id for s in manifest.sources],
    )


def verify_result(result, scope: RagScope, manifests: dict[str, IndexManifest]):
    if len({d.document_id for d in result.documents}) != len(result.documents):
        raise AgentFailure("DOCUMENT_CORRUPT", "Repeated retrieved chunk ID")
    if (
        result.fixture
        or result.requested_top_k is None
        or len(result.documents) > result.requested_top_k
    ):
        raise AgentFailure("DOCUMENT_CORRUPT", "Expected real bounded retrieval provenance")
    if result.retriever_version != "pg-cosine-exact-1" or bool(result.documents) == bool(
        result.unavailable_reason
    ):
        raise AgentFailure("DOCUMENT_CORRUPT", "Retrieval availability/version contract differs")
    pins = {p.corpus_id: p for p in scope.corpora}
    for document in result.documents:
        c = document.citation
        pin = pins.get(c.corpus_id) if c else None
        m = manifests.get(c.corpus_id) if c else None
        if (
            pin is None
            or m is None
            or not scope.permits(m.target)
            or digest(m) != pin.index_version
            or c.index_version != pin.index_version
            or c.document_id not in pin.document_ids
        ):
            raise AgentFailure(
                "DOCUMENT_NOT_AUTHORIZED", "Citation is outside the host document scope"
            )
        source = next((s for s in m.sources if s.document_id == c.document_id), None)
        span = (
            next((s for s in source.chunks if s.chunk_id == c.chunk_id), None) if source else None
        )
        if (
            span is None
            or c.model_dump(include=set(ChunkSpan.model_fields)) != span.model_dump()
            or (c.source_id, c.version, c.source_sha256, c.model_revision, c.chunker_sha256)
            != (
                source.source_id,
                source.version,
                source.version,
                m.model.revision,
                digest(m.chunker),
            )
            or (document.document_id, document.source, document.version, document.sha256)
            != (span.chunk_id, source.name, source.version, span.sha256)
            or hashlib.sha256(document.text.encode()).hexdigest() != span.sha256
            or c.score < scope.min_score
        ):
            raise AgentFailure("DOCUMENT_CORRUPT", "Citation hash/version/span differs from source")
