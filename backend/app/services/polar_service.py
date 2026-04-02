"""
Polar AccessLink API v3 Integration
Docs: https://www.polar.com/accesslink-api/
Free for all registered Polar Flow apps.
Polar-Uhren (Vantage, Pacer, Ignite, Grit X, ...) nutzen Polar Flow,
das auch direkt mit Strava synchronisiert.
"""

import base64
import httpx
from urllib.parse import urlencode
from app.core.config import settings


class PolarService:
    AUTH_URL = "https://flow.polar.com/oauth2/authorization"
    TOKEN_URL = "https://polarremote.com/v2/oauth2/token"
    API_BASE = "https://www.polaraccesslink.com/v3"

    def get_auth_url(self, state: str) -> str:
        """Generiert die Polar OAuth2 Authorization-URL."""
        params = {
            "response_type": "code",
            "client_id": settings.polar_client_id,
            "redirect_uri": settings.polar_redirect_uri,
            "scope": "accesslink.read_all",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def _basic_auth_header(self) -> str:
        """Polar verwendet HTTP Basic Auth für Token-Requests."""
        credentials = f"{settings.polar_client_id}:{settings.polar_client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access + Refresh Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": self._basic_auth_header(),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.polar_redirect_uri,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def refresh_token(self, refresh_token: str) -> dict:
        """Erneuert abgelaufenen Access Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": self._basic_auth_header(),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def register_user(self, access_token: str, polar_user_id: int) -> dict:
        """
        Registriert den User in der AccessLink-App (einmalig erforderlich).
        Muss vor dem ersten Datenzugriff aufgerufen werden.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.API_BASE}/users",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={"member-id": str(polar_user_id)},
            )
            # 409 = already registered, treat as success
            if resp.status_code not in (200, 201, 409):
                resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def get_user_info(self, access_token: str, polar_user_id: int) -> dict:
        """Lädt Nutzer-Informationen (Name, Gewicht, Größe, VO2max)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/users/{polar_user_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def list_exercises(self, access_token: str, polar_user_id: int) -> list[dict]:
        """Listet alle verfügbaren Trainings (seit letztem Pull)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Schritt 1: Transaction starten
            resp = await client.post(
                f"{self.API_BASE}/users/{polar_user_id}/exercise-transactions",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            if resp.status_code == 204:
                return []  # Keine neuen Trainings
            resp.raise_for_status()
            transaction = resp.json()
            resource_uri = transaction.get("resource-uri", "")

            # Schritt 2: Trainings aus Transaction laden
            list_resp = await client.get(
                f"{resource_uri}/exercises",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            list_resp.raise_for_status()
            exercises = list_resp.json().get("exercises", [])

            # Schritt 3: Transaction committen
            await client.put(
                f"{resource_uri}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            return exercises

    async def get_daily_activity(self, access_token: str, polar_user_id: int) -> dict:
        """Lädt Tagesaktivität (Schritte, Kalorien, aktive Zeit)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.API_BASE}/users/{polar_user_id}/activity-transactions",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            if resp.status_code == 204:
                return {}
            resp.raise_for_status()
            transaction = resp.json()
            resource_uri = transaction.get("resource-uri", "")

            list_resp = await client.get(
                f"{resource_uri}/activities",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            list_resp.raise_for_status()
            activities = list_resp.json().get("activity-log", [])

            await client.put(
                f"{resource_uri}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            return {"activities": activities}

    def exercise_to_metric(self, exercise: dict) -> dict:
        """Konvertiert Polar-Training zu internem Metrik-Format."""
        duration_str = exercise.get("duration", "PT0S")
        # ISO 8601 Dauer: PT1H30M → 90 Minuten
        import re
        hours = int(re.search(r"(\d+)H", duration_str).group(1)) if "H" in duration_str else 0
        minutes = int(re.search(r"(\d+)M", duration_str).group(1)) if "M" in duration_str else 0
        return {
            "duration_min": hours * 60 + minutes,
            "distance_m": exercise.get("distance"),
            "calories": exercise.get("calories"),
            "avg_hr": exercise.get("heart-rate", {}).get("average"),
            "max_hr": exercise.get("heart-rate", {}).get("maximum"),
            "sport": exercise.get("sport", "OTHER"),
            "date": (exercise.get("start-time") or "")[:10],
        }
