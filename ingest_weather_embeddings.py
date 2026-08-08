"""
Weather embedding ingestion pipeline.

Reads unembedded weather documents from Lakebase,
chunks the narrative text, generates embeddings using
all-MiniLM-L6-v2, and writes the vectors into
weather_embeddings using pgvector.
"""

import hashlib
import os
from datetime import datetime, timezone

from sentence_transformers import SentenceTransformer

import lakebase


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

WEATHER_DOCUMENTS_TABLE = os.environ.get(
    "WEATHER_DOCUMENTS_TABLE",
    "weather_documents",
)

WEATHER_EMBEDDINGS_TABLE = os.environ.get(
    "WEATHER_EMBEDDINGS_TABLE",
    "weather_embeddings",
)

MODEL_NAME = (
    "sentence-transformers/"
    "all-MiniLM-L6-v2"
)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


# ---------------------------------------------------------------------
# Load embedding model
# ---------------------------------------------------------------------

print(
    f"Loading embedding model: {MODEL_NAME}"
)

model = SentenceTransformer(
    MODEL_NAME
)

print("Embedding model loaded.")


# ---------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    Split text into overlapping chunks.

    Uses character-based chunks, matching the assignment's
    recommended CHUNK_SIZE=800 and CHUNK_OVERLAP=100.
    """

    if not text:
        return []

    text = text.strip()

    if len(text) <= chunk_size:
        return [text]

    chunks = []

    start = 0

    while start < len(text):

        end = start + chunk_size

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = end - overlap

    return chunks


# ---------------------------------------------------------------------
# Stable embedding ID
# ---------------------------------------------------------------------

def generate_embedding_id(
    document_id: str,
    chunk_index: int,
) -> str:
    """
    Generate a deterministic ID for a document chunk.
    """

    value = (
        f"{document_id}:{chunk_index}"
    )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------
# Read documents
# ---------------------------------------------------------------------

def get_weather_documents() -> list[dict]:
    """
    Read weather documents that do not yet have embeddings.
    """

    sql = f"""
        SELECT
            d.id,
            d.location,
            d.source_type,
            d.title,
            d.narrative_text
        FROM {WEATHER_DOCUMENTS_TABLE} d
        LEFT JOIN {WEATHER_EMBEDDINGS_TABLE} e
            ON d.id = e.document_id
        WHERE e.document_id IS NULL
        ORDER BY d.synced_at;
    """

    return lakebase.run_query(sql)


# ---------------------------------------------------------------------
# Write embeddings
# ---------------------------------------------------------------------

def insert_embeddings(
    rows: list[tuple],
) -> int:
    """
    Insert embedding rows into Lakebase.

    Embeddings are explicitly cast to VECTOR in SQL.
    """

    if not rows:
        return 0

    inserted = 0

    with lakebase.get_connection() as conn:

        with conn.cursor() as cur:

            for row in rows:

                cur.execute(
                    f"""
                    INSERT INTO {WEATHER_EMBEDDINGS_TABLE} (
                        id,
                        document_id,
                        chunk_index,
                        chunk_text,
                        embedding,
                        model_name,
                        created_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s::vector,
                        %s,
                        %s
                    )
                    ON CONFLICT (
                        document_id,
                        chunk_index
                    )
                    DO UPDATE SET
                        chunk_text =
                            EXCLUDED.chunk_text,
                        embedding =
                            EXCLUDED.embedding,
                        model_name =
                            EXCLUDED.model_name,
                        created_at =
                            EXCLUDED.created_at
                    """,
                    row,
                )

                inserted += 1

            conn.commit()

    return inserted


# ---------------------------------------------------------------------
# Main ingestion pipeline
# ---------------------------------------------------------------------

def ingest_embeddings() -> int:
    """
    Run the complete embedding pipeline.
    """

    documents = get_weather_documents()

    if not documents:

        print(
            "No unembedded weather documents found."
        )

        return 0

    print(
        f"Found {len(documents)} "
        "unembedded documents."
    )

    embedding_rows = []

    # --------------------------------------------------------------
    # Chunk documents
    # --------------------------------------------------------------

    for document in documents:

        document_id = document["id"]

        text = document.get(
            "narrative_text",
            ""
        )

        chunks = chunk_text(text)

        for chunk_index, chunk in enumerate(
            chunks
        ):

            embedding_rows.append({
                "document_id": document_id,
                "chunk_index": chunk_index,
                "chunk_text": chunk,
            })

    print(
        f"Created {len(embedding_rows)} "
        "text chunks."
    )

    if not embedding_rows:
        return 0

    # --------------------------------------------------------------
    # Generate embeddings
    # --------------------------------------------------------------

    texts = [
        row["chunk_text"]
        for row in embedding_rows
    ]

    print(
        "Generating embeddings..."
    )

    embeddings = model.encode(
        texts,
        show_progress_bar=True,
        normalize_embeddings=True,
    )

    print(
        f"Generated {len(embeddings)} "
        "embeddings."
    )

    # --------------------------------------------------------------
    # Prepare database rows
    # --------------------------------------------------------------

    now = datetime.now(
        timezone.utc
    )

    rows = []

    for row, embedding in zip(
        embedding_rows,
        embeddings,
    ):

        embedding_id = generate_embedding_id(
            row["document_id"],
            row["chunk_index"],
        )

        # Convert numpy array to a normal
        # Python list, then PostgreSQL vector
        # syntax.
        vector = (
            "["
            + ",".join(
                str(float(value))
                for value in embedding
            )
            + "]"
        )

        rows.append(
            (
                embedding_id,
                row["document_id"],
                row["chunk_index"],
                row["chunk_text"],
                vector,
                MODEL_NAME,
                now,
            )
        )

    # --------------------------------------------------------------
    # Write to Lakebase
    # --------------------------------------------------------------

    print(
        "Writing embeddings to Lakebase..."
    )

    inserted = insert_embeddings(
        rows
    )

    print(
        f"Inserted/updated {inserted} "
        "embedding rows."
    )

    return inserted


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

if __name__ == "__main__":

    count = ingest_embeddings()

    print(
        f"Embedding ingestion complete. "
        f"Rows processed: {count}"
    )