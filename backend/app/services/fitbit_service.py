"""
Fitbit Web API Integration
Docs: https://dev.fitbit.com/build/reference/web-api/
Kostenlose OAuth2 API – für Fitbit Sense, Versa, Charge, Inspire, Luxe usw.
Fitbit-Geräte können auch direkt mit Strava synchronisieren.
"""

import base64
import httpx
from urllib.parse import urlencode
from app.core.config import settings


class FitbitService:
    AUTH_URL = "https://www.fitbit.com/oauth2/authorize"
    TOKEN_URL = "https://api.fitbit.com/oauth2/token"
    API_BASE = "https://api.fitbit.com/1"

    # Benötigte Scopes für Trainings + Gesundheitsmetriken
    SCOPES = [
        "activity",
        "heartrate",
        "sleep",
        "profile",
        "weight",
        "oxygen_saturation",
        "respiratory_rate",
    ]

    def get_auth_url(self, state: str) -> str:
        """Generiert die Fitbit OAuth2 Authorization-URL."""
        params = {
            "response_type": "code",
            "client_id": settings.fitbit_client_id,
            "redirect_uri": settings.fitbit_redirect_uri,
            "scope": " ".join(self.SCOPES),
            "state": state,
            "expires_in": "604800",  # 7 Tage Token-Gültigkeit
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def _basic_auth_header(self) -> str:
        """Fitbit verwendet HTTP Basic Auth für Token-Requests."""
        credentials = f"{settings.fitbit_client_id}:{settings.fitbit_client_secret}"
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
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.fitbit_redirect_uri,
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
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_profile(self, access_token: str) -> dict:
        """Lädt Nutzerprofil (enthält user.encodedId = Fitbit-User-ID)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/user/-/profile.json",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("user", {})

    async def get_activities_today(self, access_token: str, date: str = "today") -> dict:
        """Lädt Aktivitätsdaten für ein Datum (YYYY-MM-DD oder 'today')."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/user/-/activities/date/{date}.json",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_activity_log(
        self, access_token: str, after_date: str, limit: int = 10
    ) -> list[dict]:
        """Lädt Activity-Log-Einträge (Workouts) ab einem Datum."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/user/-/activities/list.json",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "afterDate": after_date,
                    "sort": "asc",
                    "limit": limit,
                    "offset": 0,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("activities", [])

    async def get_heart_rate_today(self, access_token: str, date: str = "today") -> dict:
        """Lädt Herzfrequenzdaten (Resting HR, Zonen) für ein Datum."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/user/-/activities/heart/date/{date}/1d.json",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_sleep_today(self, access_token: str, date: str = "today") -> dict:
        """Lädt Schlafdaten für ein Datum."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/user/-/sleep/date/{date}.json",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_spo2_today(self, access_token: str, date: str = "today") -> dict:
        """Lädt SpO2-Daten (Blutsauerstoff) für ein Datum."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.fitbit.com/1/user/-/spo2/date/{date}.json",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    def activity_to_training_plan_update(self, activity: dict) -> dict:
        """Konvertiert Fitbit-Aktivität zu TrainingPlan-Update."""
        duration_ms = activity.get("duration", 0)
        return {
            "date": (activity.get("startTime") or "")[:10],
            "avg_hr": activity.get("averageHeartRate"),
            "duration_min": round(duration_ms / 60000),
        }

    def activity_to_metric(self, activity: dict) -> dict:
        """Konvertiert Fitbit-Aktivität zu internem Metrik-Format."""
        duration_ms = activity.get("duration", 0)
        return {
            "duration_min": round(duration_ms / 60000),
            "distance_m": activity.get("distance"),
            "calories": activity.get("calories"),
            "avg_hr": activity.get("averageHeartRate"),
            "sport": activity.get("activityName", "OTHER"),
            "date": (activity.get("startTime") or "")[:10],
        }

    def parse_resting_hr(self, hr_data: dict) -> int | None:
        """Extrahiert Ruhepuls aus Herzfrequenz-Response."""
        try:
            summary = hr_data["activities-heart"][0]["value"]
            return summary.get("restingHeartRate")
        except (KeyError, IndexError, TypeError):
            return None

    def parse_sleep(self, sleep_data: dict) -> dict:
        """Extrahiert Schlafdaten aus Sleep-Response."""
        summary = sleep_data.get("summary", {})
        return {
            "sleep_duration_min": summary.get("totalMinutesAsleep"),
            "sleep_quality_score": None,  # Fitbit liefert Sleep-Stages, kein Score
        }
