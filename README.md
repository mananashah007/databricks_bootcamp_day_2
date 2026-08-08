# Weather Intelligence — Unstructured Data to Lakebase Vector Search

## Overview

This project builds an end-to-end weather intelligence pipeline using the
National Weather Service (NWS) API, Databricks Lakebase, PostgreSQL/pgvector,
and sentence-transformers.

The pipeline:

1. Harvests unstructured weather alerts and forecasts from the NWS API.
2. Stores the normalized weather documents in Lakebase.
3. Chunks and embeds the weather narratives.
4. Stores the resulting vectors in Lakebase using pgvector.
5. Performs semantic similarity search through a Flask REST API.

---

## Data Source

### National Weather Service API

The project uses the National Weather Service API:

`https://api.weather.gov`

The NWS API was selected because it is free, does not require an API key,
and provides rich narrative weather information suitable for semantic
search.

The application uses:

- NWS `/points/{lat},{lon}` to resolve locations to NWS grid points.
- NWS `/alerts/active` to retrieve active weather alerts.
- NWS forecast endpoints to retrieve multi-period narrative forecasts.

A local `data.json` file containing major US cities and their latitude and
longitude is used to resolve locations such as:

1. Chicago, IL
2. Austin, TX
3. New York, NY
4. Los Angeles, CA
