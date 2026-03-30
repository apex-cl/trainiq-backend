"""
Garmin Connect API Integration
Docs: https://developer.garmin.com/health-api/overview/
"""

import httpx
from datetime import datetime, timezone
from app.core.config import settings


class GarminService:
    AUTH_URL = "https://connect.garmin.com/oauthConfirm"
    TOKEN_URL = "https://connectapi.garmin.com/oauth-service/oauth/token"
    API_BASE = "https://connectapi.garmin.com"

    def get_auth_url(self, state: str) -> str:
        """Generiert die OAuth-URL für Garmin."""
        callback = f"{settings.frontend_url}/api/watch/garmin/callback"
        params = {
            "oauth_token": settings.garmin_client_id,
            "oauth_callback": callback,
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.AUTH_URL}?{query}"

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access + Refresh Token."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.garmin_client_id,
                    "client_secret": settings.garmin_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def refresh_token(self, refresh_token: str) -> dict:
        """Erneuert abgelaufenen Access Token."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.garmin_client_id,
                    "client_secret": settings.garmin_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_daily_summary(self, access_token: str, date: str) -> dict:
        """Lädt tägliche Zusammenfassung für ein Datum."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.API_BASE}/wellness-api/rest/dailies",
                headers=headers,
                params={"startDate": date, "endDate": date},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_sleep_data(self, access_token: str, date: str) -> dict:
        """Lädt Schlafdaten für ein Datum."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.API_BASE}/wellness-api/rest/sleeps",
                headers=headers,
                params={"startDate": date, "endDate": date},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_activities(
        self, access_token: str, start_date: str, end_date: str
    ) -> list[dict]:
        """Lädt Aktivitäten für einen Zeitraum."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.API_BASE}/wellness-api/rest/activities",
                headers=headers,
                params={"startDate": start_date, "endDate": end_date},
            )
            resp.raise_for_status()
            return resp.json()

    def activity_to_metric(self, activity: dict) -> dict:
        """Konvertiert Garmin-Aktivität zu Metrik."""
        return {
            "duration_min": round(activity.get("duration", 0) / 60),
            "steps": activity.get("steps"),
            "distance": activity.get("distance"),
            "calories": activity.get("calories"),
        }
