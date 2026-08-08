-- ============================================================
-- Weather Intelligence
-- Create weather_documents table
-- ============================================================

CREATE TABLE IF NOT EXISTS weather_documents (
    id TEXT PRIMARY KEY,
    location TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT,
    narrative_text TEXT NOT NULL,
    issued_at TIMESTAMPTZ,
    effective_at TIMESTAMPTZ,
    payload JSONB,
    synced_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);