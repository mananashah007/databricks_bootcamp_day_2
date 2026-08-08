-- ============================================================
-- Weather Intelligence
-- Create weather_embeddings table and vector index
-- ============================================================

-- pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;


CREATE TABLE IF NOT EXISTS weather_embeddings (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    model_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_weather_document
        FOREIGN KEY (document_id)
        REFERENCES weather_documents(id)
        ON DELETE CASCADE,

    CONSTRAINT unique_document_chunk
        UNIQUE (document_id, chunk_index)
);


-- HNSW index for cosine similarity search
CREATE INDEX IF NOT EXISTS idx_weather_embeddings_vector
ON weather_embeddings
USING hnsw (embedding vector_cosine_ops);