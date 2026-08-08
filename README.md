# Weather Intelligence — Unstructured Data → Lakebase Vector Search → REST API

## Overview

This project builds an end-to-end weather intelligence pipeline using the
National Weather Service (NWS) API, Databricks Lakebase, PostgreSQL/pgvector,
and `sentence-transformers`.

The pipeline:

1. Harvests unstructured weather alerts and forecasts from the NWS API.
2. Normalizes and stores the weather documents in Lakebase.
3. Chunks and embeds the weather narratives.
4. Stores the embeddings in Lakebase using pgvector.
5. Performs semantic search over the weather documents through a Flask REST API.

### Architecture


                        NWS API
                           |
                           v
                  weather_client.py
                           |
                           v
                  POST /weather/sync
                           |
                           v
                  weather_documents
                           |
                           v
            ingest_weather_embeddings.py
                           |
                  Chunk + Embed
                           |
                           v
                  weather_embeddings
                           |
                           v
                 POST /weather/search
                           |
                           v
                  pgvector <=> Search