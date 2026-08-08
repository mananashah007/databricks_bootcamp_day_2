"""
weather_service.py

Business logic for harvesting weather data and persisting
normalized weather documents into Lakebase.
"""

import json
from typing import Any

from weather_client import WeatherClient
from lakebase import run_write


class WeatherService:
    """Handles weather harvesting and Lakebase persistence."""

    def __init__(self):
        self.client = WeatherClient()

    def sync_location(self, location: str) -> int:
        """
        Harvest weather documents for a single location
        and upsert them into Lakebase.

        Returns the number of documents processed.
        """

        documents = self.client.harvest_location(location)

        for document in documents:
            self._upsert_document(document)

        return len(documents)

    def sync_locations(
        self,
        locations: list[str],
        limit: int | None = None,
    ) -> int:
        """
        Harvest and persist weather documents for multiple locations.

        If limit is supplied, stop after processing that many
        documents.
        """

        total = 0

        for location in locations:

            if limit is not None and total >= limit:
                break

            documents = self.client.harvest_location(location)

            for document in documents:

                if limit is not None and total >= limit:
                    break

                self._upsert_document(document)

                total += 1

        return total

    def _upsert_document(
        self,
        document: dict[str, Any],
    ) -> None:
        """
        Insert a weather document or update it if the document
        already exists.

        The document ID is generated deterministically by
        WeatherClient, so repeated syncs do not create duplicates.
        """

        sql = """
            INSERT INTO weather_documents (
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
                %s::jsonb,
                %s
            )
            ON CONFLICT (id)
            DO UPDATE SET
                location = EXCLUDED.location,
                source_type = EXCLUDED.source_type,
                title = EXCLUDED.title,
                narrative_text = EXCLUDED.narrative_text,
                issued_at = EXCLUDED.issued_at,
                effective_at = EXCLUDED.effective_at,
                payload = EXCLUDED.payload,
                synced_at = EXCLUDED.synced_at;
        """

        params = (
            document["id"],
            document["location"],
            document["source_type"],
            document["title"],
            document["narrative_text"],
            document["issued_at"],
            document["effective_at"],
            json.dumps(document["payload"]),
            document["synced_at"],
        )

        run_write(sql, params)