-- ============================================================
-- Weather Intelligence
-- Verification queries
-- ============================================================


-- Check weather documents
SELECT
    id,
    location,
    source_type,
    headline,
    narrative_text,
    issued_at,
    effective_at,
    synced_at
FROM weather_documents
ORDER BY synced_at DESC
LIMIT 20;


-- Count weather documents
SELECT COUNT(*) AS weather_document_count
FROM weather_documents;


-- Check embeddings
SELECT
    id,
    document_id,
    chunk_index,
    LEFT(chunk_text, 100) AS chunk_preview,
    model_name,
    created_at
FROM weather_embeddings
ORDER BY created_at DESC
LIMIT 20;


-- Count embeddings
SELECT COUNT(*) AS embedding_count
FROM weather_embeddings;


-- Check table schema
SELECT
    column_name,
    data_type,
    udt_name
FROM information_schema.columns
WHERE table_name IN (
    'weather_documents',
    'weather_embeddings'
)
ORDER BY table_name, ordinal_position;