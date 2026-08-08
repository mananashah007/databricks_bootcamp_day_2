"""
Weather Intelligence API

Pipeline:

    National Weather Service API
              ↓
       weather_client.py
              ↓
          Flask API
              ↓
        Lakebase/Postgres
              ↓
       weather_documents

Endpoints:

    GET  /healthz
    POST /weather/sync

The vector search endpoint will be added in the next step.
"""

import json
import logging
import os

import requests
from flask import Flask, jsonify, request

from lakebase import run_query, get_connection
from weather_client import WeatherClient


# ---------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("weather-app")

app = Flask(__name__)


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

WEATHER_TABLE_NAME = os.environ.get(
    "WEATHER_TABLE_NAME",
    "weather_documents",
)


# =====================================================================
# LAKEBASE TABLE SETUP
# =====================================================================

def ensure_weather_table():
    """
    Create the weather_documents table and supporting indexes
    if they don't already exist.
    """

    lakebase.run_write(
        f"""
        CREATE TABLE IF NOT EXISTS {WEATHER_TABLE_NAME} (
            id TEXT PRIMARY KEY,
            location TEXT NOT NULL,
            source_type TEXT NOT NULL,
            title TEXT,
            narrative_text TEXT NOT NULL,
            issued_at TIMESTAMPTZ,
            effective_at TIMESTAMPTZ,
            payload JSONB NOT NULL,
            synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    lakebase.run_write(
        f"""
        CREATE INDEX IF NOT EXISTS
        idx_{WEATHER_TABLE_NAME}_location
        ON {WEATHER_TABLE_NAME} (location)
        """
    )

    lakebase.run_write(
        f"""
        CREATE INDEX IF NOT EXISTS
        idx_{WEATHER_TABLE_NAME}_source_type
        ON {WEATHER_TABLE_NAME} (source_type)
        """
    )


# =====================================================================
# HEALTH CHECK
# =====================================================================

@app.route("/healthz", methods=["GET"])
def healthz():
    """
    Basic health check endpoint.
    """

    return jsonify({
        "status": "ok"
    })


# =====================================================================
# WEATHER SYNC
# =====================================================================

@app.route("/weather/sync", methods=["POST"])
def sync_weather():
    """
    Harvest weather data from the NWS API and write it to Lakebase.

    Expected request body:

    {
        "locations": [
            "Chicago, IL",
            "Austin, TX"
        ],
        "limit": 50
    }

    The limit is the maximum number of documents synced across
    all requested locations.
    """

    # Make sure the destination table exists.
    ensure_weather_table()

    # --------------------------------------------------------------
    # Parse request body
    # --------------------------------------------------------------

    body = (
        request.get_json(silent=True)
        or {}
    )

    locations = body.get(
        "locations",
        []
    )

    limit = body.get(
        "limit",
        50
    )

    # --------------------------------------------------------------
    # Validate locations
    # --------------------------------------------------------------

    if not isinstance(
        locations,
        list
    ):

        return jsonify({
            "error": "locations must be a list"
        }), 400

    if not locations:

        return jsonify({
            "error": (
                "locations must be a "
                "non-empty list"
            )
        }), 400

    # Clean location strings.

    locations = [
        location.strip()
        for location in locations
        if isinstance(
            location,
            str
        )
        and location.strip()
    ]

    if not locations:

        return jsonify({
            "error": (
                "locations must contain "
                "valid location strings"
            )
        }), 400

    # --------------------------------------------------------------
    # Validate limit
    # --------------------------------------------------------------

    try:

        limit = int(limit)

    except (
        TypeError,
        ValueError
    ):

        return jsonify({
            "error": "limit must be an integer"
        }), 400

    if limit < 1:

        return jsonify({
            "error": (
                "limit must be greater than 0"
            )
        }), 400

    # Put a reasonable upper bound on the request.

    limit = min(
        limit,
        500
    )

    # --------------------------------------------------------------
    # Harvest weather data
    # --------------------------------------------------------------

    client = WeatherClient()

    total_synced = 0

    location_results = []

    for location in locations:

        # Stop once the overall limit is reached.

        if total_synced >= limit:
            break

        try:

            documents = client.harvest_location(
                location
            )

        except ValueError as exc:

            logger.warning(
                "Could not resolve location %s: %s",
                location,
                exc
            )

            return jsonify({
                "error": str(exc),
                "location": location
            }), 400

        except requests.RequestException as exc:

            logger.exception(
                "NWS API request failed for %s",
                location
            )

            return jsonify({
                "error": (
                    "NWS API request failed"
                ),
                "location": location,
                "details": str(exc)
            }), 502

        # ----------------------------------------------------------
        # Apply overall document limit
        # ----------------------------------------------------------

        remaining = (
            limit - total_synced
        )

        documents = documents[
            :remaining
        ]

        # ----------------------------------------------------------
        # Write documents to Lakebase
        # ----------------------------------------------------------

        synced = _upsert_weather_batch(
            documents
        )

        total_synced += synced

        location_results.append({
            "location": location,
            "documents": synced
        })

    # --------------------------------------------------------------
    # Response
    # --------------------------------------------------------------

    return jsonify({
        "status": "success",
        "synced": total_synced,
        "locations": location_results
    })


# =====================================================================
# WEATHER DOCUMENT UPSERT
# =====================================================================

def _upsert_weather_batch(
    documents: list[dict]
) -> int:
    """
    Upsert normalized weather documents into Lakebase.

    WeatherClient generates deterministic IDs, so running the
    sync multiple times will update existing records rather than
    create duplicates.
    """

    if not documents:
        return 0

    count = 0

    with lakebase.get_connection() as conn:

        with conn.cursor() as cur:

            for document in documents:

                cur.execute(
                    f"""
                    INSERT INTO {WEATHER_TABLE_NAME} (
                        id,
                        location,
                        source_type,
                        title,
                        narrative_text,
                        issued_at,
                        effective_at,
                        payload,
                        synced_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )

                    ON CONFLICT (id)
                    DO UPDATE SET

                        location =
                            EXCLUDED.location,

                        source_type =
                            EXCLUDED.source_type,

                        title =
                            EXCLUDED.title,

                        narrative_text =
                            EXCLUDED.narrative_text,

                        issued_at =
                            EXCLUDED.issued_at,

                        effective_at =
                            EXCLUDED.effective_at,

                        payload =
                            EXCLUDED.payload,

                        synced_at =
                            EXCLUDED.synced_at
                    """,
                    (
                        document["id"],
                        document["location"],
                        document["source_type"],
                        document.get("title"),
                        document["narrative_text"],
                        document.get("issued_at"),
                        document.get("effective_at"),
                        json.dumps(
                            document["payload"]
                        ),
                        document["synced_at"],
                    )
                )

                count += 1

            conn.commit()

    return count

@app.route("/weather/search", methods=["POST"])
def search_weather():
    """
    Semantic search over weather documents using pgvector cosine similarity.

    Request:
    {
        "query": "risk of flooding near rivers",
        "top_k": 5
    }
    """

    data = request.get_json(silent=True) or {}

    query = data.get("query")

    if not isinstance(query, str) or not query.strip():
        return jsonify({
            "error": "query must be a non-empty string"
        }), 400

    query = query.strip()

    try:
        top_k = int(data.get("top_k", 5))
    except (TypeError, ValueError):
        return jsonify({
            "error": "top_k must be an integer"
        }), 400

    # Clamp top_k to 1–20
    top_k = max(1, min(top_k, 20))

    try:
        # ----------------------------------------------------------
        # Generate query embedding
        # ----------------------------------------------------------

        query_embedding = embedding_model.encode(
            query,
            normalize_embeddings=True
        )

        # Convert numpy array to pgvector array literal
        vector_string = (
            "["
            + ",".join(
                str(float(value))
                for value in query_embedding
            )
            + "]"
        )

        # ----------------------------------------------------------
        # Semantic search
        # ----------------------------------------------------------

        sql = """
            SELECT
                d.id,
                d.location,
                d.title,
                d.narrative_text,
                e.chunk_text,
                1 - (
                    e.embedding <=> %s::vector
                ) AS similarity
            FROM weather_embeddings e
            JOIN weather_documents d
                ON d.id = e.document_id
            ORDER BY
                e.embedding <=> %s::vector
            LIMIT %s;
        """

        rows = run_query(
            sql,
            (
                vector_string,
                vector_string,
                top_k,
            )
        )

        # ----------------------------------------------------------
        # Return results
        # ----------------------------------------------------------

        results = []

        for row in rows:
            results.append({
                "id": row["id"],
                "location": row["location"],
                "title": row["headline"],
                "narrative_text": row["narrative_text"],
                "chunk_text": row["chunk_text"],
                "similarity": float(
                    row["similarity"]
                ),
            })

        return jsonify({
            "query": query,
            "top_k": top_k,
            "count": len(results),
            "results": results,
        })

    except Exception as exc:

        app.logger.exception(
            "Weather semantic search failed"
        )

        return jsonify({
            "error": "Weather search failed",
            "details": str(exc),
        }), 500



# =====================================================================
# APPLICATION ENTRY POINT
# =====================================================================

if __name__ == "__main__":

    host = os.getenv(
        "FLASK_RUN_HOST",
        "0.0.0.0"
    )

    port = int(
        os.getenv(
            "FLASK_RUN_PORT",
            8000
        )
    )

    app.run(
        host=host,
        port=port,
        debug=True
    )