"""P6A immutable document snapshots, pinned indexes, exact pgvector retrieval."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE rag.corpora (
        corpus_id TEXT PRIMARY KEY, target JSONB NOT NULL
    )""")
    op.execute("""CREATE TABLE rag.sources (
        corpus_id TEXT NOT NULL REFERENCES rag.corpora(corpus_id),
        document_id TEXT NOT NULL, info JSONB NOT NULL, raw BYTEA NOT NULL,
        CHECK (octet_length(raw)<=262144), PRIMARY KEY(corpus_id,document_id)
    )""")
    op.execute("""CREATE TABLE rag.indexes (
        corpus_id TEXT NOT NULL REFERENCES rag.corpora(corpus_id),
        index_version TEXT NOT NULL, manifest JSONB NOT NULL,
        PRIMARY KEY(corpus_id,index_version)
    )""")
    op.execute("""CREATE TABLE rag.chunks (
        corpus_id TEXT NOT NULL, index_version TEXT NOT NULL,
        chunk_id TEXT NOT NULL, document_id TEXT NOT NULL,
        span JSONB NOT NULL, text TEXT NOT NULL CHECK (length(text)<=256),
        embedding public.vector(512) NOT NULL, embedding_sha256 TEXT NOT NULL,
        PRIMARY KEY(corpus_id,index_version,chunk_id),
        FOREIGN KEY(corpus_id,index_version) REFERENCES rag.indexes,
        FOREIGN KEY(corpus_id,document_id) REFERENCES rag.sources
    )""")
    op.execute("CREATE INDEX rag_chunk_scope ON rag.chunks(corpus_id,index_version,document_id)")
    op.execute("GRANT USAGE ON SCHEMA rag TO datapilot_rag_reader,datapilot_rag_ingest")
    for table in ("corpora", "sources", "indexes", "chunks"):
        op.execute(f"GRANT SELECT ON rag.{table} TO datapilot_rag_reader")
        op.execute(f"GRANT SELECT,INSERT ON rag.{table} TO datapilot_rag_ingest")


def downgrade():
    raise RuntimeError("Retain historical RAG indexes; destructive cleanup needs separate approval")
