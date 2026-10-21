"""Trusted source approval/deployment controls; none are registered as model tools."""

from pathlib import Path

from datapilot.config import Settings
from datapilot.db.management import management_url
from datapilot.rag.contracts import Chunker, RagScope, Target
from datapilot.rag.mcp import rag_session
from datapilot.rag.models import LocalEmbedding, fetch_model
from datapilot.rag.storage import IngestionService, make_pin


def read_scope(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Scope file exceeds quota")
    return RagScope.model_validate_json(raw)


def add_commands(sub):
    parser = sub.add_parser("rag", help="Approved local documents and read-only pgvector retrieval")
    actions = parser.add_subparsers(dest="rag_command", required=True)
    actions.add_parser("model-fetch", help="Explicit pinned public CPU model download")
    ingest = actions.add_parser("ingest", help="Trusted append-only document/index ingestion")
    ingest.add_argument("--corpus", required=True)
    ingest.add_argument("--file", type=Path, action="append", required=True)
    ingest.add_argument("--owner", default="local-user")
    target = ingest.add_mutually_exclusive_group(required=True)
    target.add_argument("--saas", action="store_true")
    target.add_argument("--dataset")
    ingest.add_argument("--dataset-version", type=int)
    ingest.add_argument("--reviewed", action="store_true")
    ingest.add_argument("--chunk-chars", type=int, default=192)
    ingest.add_argument("--output", type=Path, required=True, help="New artifacts/ scope JSON")
    query = actions.add_parser("query", help="Only read-only MCP search; no SQL parameters")
    query.add_argument("--scope", type=Path, required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--top-k", type=int, default=3)


async def run(args):
    if args.rag_command == "model-fetch":
        fetch_model()
        return {"status": "pinned_model_verified"}
    settings = Settings(llm_mode="fake")
    if args.rag_command == "query":
        async with rag_session(settings, read_scope(args.scope)) as tools:
            return (await tools.search(args.query, args.top_k)).model_dump(mode="json")
    from datapilot.datasets.contracts import DatasetBinding, DatasetScope
    from datapilot.runtime.mcp_client import dataset_session

    root = Path(__file__).resolve().parents[3]
    destination = args.output.resolve()
    if not destination.is_relative_to(root / "artifacts") or destination.exists():
        raise ValueError("Write a new scope file under this repository's artifacts directory")
    target = Target(
        corpus_id=args.corpus,
        owner=args.owner,
        dataset_id=args.dataset,
        dataset_version=args.dataset_version,
    )
    scope = RagScope(
        owner=args.owner,
        allow_saas=args.saas,
        datasets=DatasetScope(
            bindings=[DatasetBinding(dataset_id=args.dataset, version=args.dataset_version)]
            if args.dataset
            else []
        ),
    )
    if not args.reviewed:
        raise ValueError("Explicit review of sources and target is required")
    if args.dataset:
        async with dataset_session(settings, scope.datasets) as tools:
            await tools.schema(args.dataset)  # Verify ready Dataset/version via the existing MCP.
    service = IngestionService(management_url("rag_ingest"), LocalEmbedding())
    try:
        manifest, version, reused, usage = service.ingest(
            target, args.file, scope=scope, reviewed=True, chunker=Chunker(chars=args.chunk_chars)
        )
        scope.corpora = [make_pin(manifest, version)]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(scope.model_dump_json(indent=2) + "\n")
        return {
            "status": "ready",
            "corpus_id": target.corpus_id,
            "index_version": version,
            "reused": reused,
            "embedding_usage": usage.model_dump() if usage else None,
            "scope_file": str(destination),
        }
    finally:
        service.close()
