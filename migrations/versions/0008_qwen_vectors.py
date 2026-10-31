"""Append native 1024-dimensional vectors; retain all legacy 512-dimensional data."""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE rag.chunks_1024 (
        corpus_id TEXT NOT NULL, index_version TEXT NOT NULL,
        chunk_id TEXT NOT NULL, document_id TEXT NOT NULL,
        span JSONB NOT NULL, text TEXT NOT NULL CHECK (length(text)<=256),
        embedding public.vector(1024) NOT NULL, embedding_sha256 TEXT NOT NULL,
        PRIMARY KEY(corpus_id,index_version,chunk_id),
        FOREIGN KEY(corpus_id,index_version) REFERENCES rag.indexes,
        FOREIGN KEY(corpus_id,document_id) REFERENCES rag.sources
    )""")
    op.execute(
        "CREATE INDEX rag_chunk_1024_scope ON rag.chunks_1024(corpus_id,index_version,document_id)"
    )
    op.execute("GRANT SELECT ON rag.chunks_1024 TO datapilot_rag_reader")
    op.execute("GRANT SELECT,INSERT ON rag.chunks_1024 TO datapilot_rag_ingest")


def downgrade():
    raise RuntimeError("Retain historical indexes; destructive cleanup requires separate approval")
