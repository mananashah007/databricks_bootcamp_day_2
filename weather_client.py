"""
weather_client.py

NWS API Harvester & Normalizer for weather alerts and forecasts.

The National Weather Service API does not require an API key.
Supported locations are maintained in data/us_cities.json.
"""
import os
import hashlib
from typing import Any, Dict, List, Optional, Tuple
import re
import json
from datetime import datetime, timezone

import requests

_BASE_URL = os.environ.get(
    "WEATHER_API_BASE_URL",
    "https://api.weather.gov",
)
_DEFAULT_TIMEOUT = 30

class WeatherClient:
    """Harvests and normalizes NWS weather alerts and forecasts."""

    def __init__(
        self,
        city_data_path: Optional[str] = None,
        contact_info: str = "mshah959@gmail.com",
        base_url: Optional[str] = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ):
        self.base_url = (base_url or _BASE_URL).rstrip("/")
        self.timeout = timeout

        # Reuse a single HTTP session for all NWS requests.
        self._session = requests.Session()

        self._session.headers.update(
            {
                "User-Agent": (
                    f"(DatabricksWeatherRAG/1.0, {contact_info})"
                ),
                "Accept": "application/geo+json",
            }
        )

        # Load supported city coordinates.
        self.city_lookup: Dict[str, Tuple[float, float]] = {}

        if city_data_path is None:
            city_data_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "data",
                "data.json",
        )

        if not os.path.exists(city_data_path):
            raise FileNotFoundError(
                f"City data file not found: {city_data_path}"
        )
        self._load_city_lookup(city_data_path)
    # ------------------------------------------------------------------
    # Location handling
    # ------------------------------------------------------------------

    def _load_city_lookup(self, file_path: str) -> None:
        """Load city coordinates from the JSON configuration file."""

        with open(file_path, "r", encoding="utf-8") as f:
            cities = json.load(f)

        for city in cities:
            name = city.get("display_name", "").strip().lower()

            if name:
                self.city_lookup[name] = (
                    float(city["lat"]),
                    float(city["lon"]),
                )    

    def resolve_location(
        self,
        location: str,
    ) -> Tuple[str, float, float]:
        """
        Resolve a location into:

        (display_name, latitude, longitude)

        Supports either:

        - "Chicago, IL"
        - "41.8781, -87.6298"
        """

        loc_str = location.strip()

        # --------------------------------------------------------------
        # Direct latitude / longitude
        # --------------------------------------------------------------

        coord_match = re.match(
            r"^([\-\+]?\d+\.?\d*)\s*,\s*([\-\+]?\d+\.?\d*)$",
            loc_str,
        )

        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))

            return (
                f"{lat:.4f}, {lon:.4f}",
                lat,
                lon,
            )

        # --------------------------------------------------------------
        # City lookup
        # --------------------------------------------------------------

        lookup_key = loc_str.lower()

        if lookup_key in self.city_lookup:
            lat, lon = self.city_lookup[lookup_key]

            return (
                loc_str,
                lat,
                lon,
            )

        raise ValueError(
            f"Could not resolve location '{location}' "
            "to lat/lon coordinates."
        )

    # ------------------------------------------------------------------
    # Utility functions
    # ------------------------------------------------------------------

    def _generate_stable_id(
        self,
        source_type: str,
        raw_key: str,
    ) -> str:
        """
        Generate a deterministic SHA256 ID.

        This allows weather documents to be safely upserted without
        creating duplicates when the sync job runs again.
        """

        seed = f"{source_type}:{raw_key}".encode("utf-8")

        return hashlib.sha256(seed).hexdigest()

    # ------------------------------------------------------------------
    # NWS API requests
    # ------------------------------------------------------------------

    def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Perform a GET request against the NWS API.
        """

        response = self._session.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def fetch_alerts(
        self,
        display_name: str,
        lat: float,
        lon: float,
    ) -> List[Dict[str, Any]]:
        """
        Fetch active weather alerts for a location and normalize
        them into weather document records.
        """

        data = self.get(
            "/alerts/active",
            params={
                "point": f"{lat:.4f},{lon:.4f}",
            },
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        documents = []

        for feature in data.get("features", []):

            props = feature.get("properties", {})

            # Prefer the alert's official ID.
            raw_id = (
                props.get("id")
                or feature.get("id")
                or f"{lat},{lon}_{props.get('sent')}"
            )

            # ----------------------------------------------------------
            # Combine description + instruction
            # ----------------------------------------------------------

            narrative_parts = []

            description = props.get("description")

            if description:
                narrative_parts.append(
                    description.strip()
                )

            instruction = props.get("instruction")

            if instruction:
                narrative_parts.append(
                    f"INSTRUCTIONS:\n{instruction.strip()}"
                )

            narrative_text = "\n\n".join(
                narrative_parts
            )

            if not narrative_text:
                narrative_text = (
                    props.get("headline")
                    or "No details available."
                )

            # ----------------------------------------------------------
            # Normalized document
            # ----------------------------------------------------------

            document = {
                "id": self._generate_stable_id(
                    "alert",
                    raw_id,
                ),

                "location": display_name,

                "source_type": "alert",

                "title": (
                    props.get("event")
                    or props.get("headline")
                    or "Weather Alert"
                ),

                "narrative_text": narrative_text,

                "issued_at": (
                    props.get("sent")
                    or props.get("effective")
                ),

                "effective_at": (
                    props.get("effective")
                    or props.get("onset")
                ),

                "payload": feature,

                "synced_at": now_iso,
            }

            documents.append(document)

        return documents

    # ------------------------------------------------------------------
    # Forecasts
    # ------------------------------------------------------------------

    def fetch_forecasts(
        self,
        display_name: str,
        lat: float,
        lon: float,
    ) -> List[Dict[str, Any]]:
        """
        Fetch multi-period NWS forecasts and normalize them into
        weather document records.
        """

        # --------------------------------------------------------------
        # Resolve coordinates to NWS grid point
        # --------------------------------------------------------------

        points_data = self.get(
            f"/points/{lat:.4f},{lon:.4f}"
        )

        forecast_url = (
            points_data
            .get("properties", {})
            .get("forecast")
        )

        if not forecast_url:
            return []

        # --------------------------------------------------------------
        # Fetch forecast
        # --------------------------------------------------------------

        response = self._session.get(
            forecast_url,
            timeout=self.timeout,
        )

        response.raise_for_status()

        forecast_data = response.json()

        periods = (
            forecast_data
            .get("properties", {})
            .get("periods", [])
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        documents = []

        for period in periods:

            start_time = period.get(
                "startTime",
                "",
            )

            period_name = period.get(
                "name",
                "Forecast Period",
            )

            # Stable key for deduplication.
            raw_id = (
                f"{display_name}_"
                f"{start_time}_"
                f"{period_name}"
            )

            narrative_text = (
                period.get("detailedForecast")
                or period.get("shortForecast")
                or ""
            )

            document = {
                "id": self._generate_stable_id(
                    "forecast",
                    raw_id,
                ),

                "location": display_name,

                "source_type": "forecast",

                "title": (
                    f"{display_name} Forecast - "
                    f"{period_name}"
                ),

                "narrative_text": narrative_text,

                "issued_at": start_time,

                "effective_at": period.get(
                    "startTime"
                ),

                "payload": period,

                "synced_at": now_iso,
            }

            documents.append(document)

        return documents

    # ------------------------------------------------------------------
    # Harvest a single location
    # ------------------------------------------------------------------

    def harvest_location(
        self,
        location_str: str,
    ) -> List[Dict[str, Any]]:
        """
        Resolve a location and collect both:

        - Active weather alerts
        - Multi-period forecasts
        """

        display_name, lat, lon = self.resolve_location(
            location_str
        )

        documents = []

        # --------------------------------------------------------------
        # Alerts
        # --------------------------------------------------------------

        try:
            alerts = self.fetch_alerts(
                display_name,
                lat,
                lon,
            )

            documents.extend(alerts)

        except requests.RequestException as exc:
            print(
                f"Alert request failed for "
                f"{display_name}: {exc}"
            )

        # --------------------------------------------------------------
        # Forecast
        # --------------------------------------------------------------

        try:
            forecasts = self.fetch_forecasts(
                display_name,
                lat,
                lon,
            )

            documents.extend(forecasts)

        except requests.RequestException as exc:
            print(
                f"Forecast request failed for "
                f"{display_name}: {exc}"
            )

        return documents

    # ------------------------------------------------------------------
    # Harvest multiple locations
    # ------------------------------------------------------------------

    def harvest_locations(
        self,
        locations: List[str],
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Harvest weather documents for multiple locations.

        If limit is supplied, return at most that many documents.
        """

        all_documents = []

        for location in locations:

            try:

                documents = self.harvest_location(
                    location
                )

                all_documents.extend(documents)

            except ValueError as exc:

                print(
                    f"Skipping invalid location "
                    f"{location}: {exc}"
                )

            except requests.RequestException as exc:

                print(
                    f"Request failed for "
                    f"{location}: {exc}"
                )

            if limit and len(all_documents) >= limit:
                break

        if limit:
            return all_documents[:limit]

        return all_documents
