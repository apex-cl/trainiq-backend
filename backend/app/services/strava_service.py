"""
Strava API Integration
Docs: https://developers.strava.com/docs/reference/
"""
import httpx
from datetime import datetime, timezone
from urllib.parse import urlencode
from app.core.config import settings


class StravaService:
    AUTH_URL = "https://www.strava.com/oauth/authorize"
    TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
    API_BASE  = "https://www.strava.com/api/v3"

    def get_auth_url(self, state: str) -> str:
        """Generiert die OAuth-URL für den Browser."""
        params = {
            "client_id": settings.strava_client_id,
            "redirect_uri": settings.strava_redirect_uri,
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": "read,activity:read_all",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access + Refresh Token."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(self.TOKEN_URL, data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "code": code,
                "grant_type": "authorization_code",
            })
            resp.raise_for_status()
            return resp.json()

    async def refresh_token(self, refresh_token: str) -> dict:
        """Erneuert abgelaufenen Access Token."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(self.TOKEN_URL, data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            })
            resp.raise_for_status()
            return resp.json()

    async def get_athlete(self, access_token: str) -> dict:
        """Lädt Athlete-Profil."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.API_BASE}/athlete",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_recent_activities(self, access_token: str, limit: int = 10) -> list[dict]:
        """Lädt letzte Aktivitäten (max 200 pro Request)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.API_BASE}/athlete/activities",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"per_page": limit},
            )
            resp.raise_for_status()
            return resp.json()

    def activity_to_training_plan_update(self, activity: dict) -> dict:
        """
        Konvertiert Strava-Aktivität zu TrainingPlan-Update.
        Gibt zurück: {date, workout_type, duration_min, avg_hr, status: "completed"}
        """
        sport_map = {
            "Run": "Laufen",
            "Ride": "Radfahren",
            "Swim": "Schwimmen",
            "Walk": "Gehen",
            "Hike": "Wandern",
            "WeightTraining": "Krafttraining",
        }
        workout_type = sport_map.get(activity.get("type", ""), "Sonstiges")
        duration_min = round(activity.get("elapsed_time", 0) / 60)
        avg_hr = activity.get("average_heartrate")
        start_date = activity.get("start_date_local", "")[:10]  # "2024-03-17"

        return {
            "date": start_date,
            "workout_type": workout_type,
            "duration_min": duration_min,
            "avg_hr": avg_hr,
            "status": "completed",
            "strava_id": activity.get("id"),
        }
