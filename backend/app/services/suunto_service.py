"""
Suunto App API Integration
Docs: https://apizone.suunto.com/
Kostenlose OAuth2 API für Suunto-Uhren (Vertical, Race, Peak, Wing, 9 Pro, Spartan usw.)
Suunto-Uhren synchronisieren auch direkt mit Strava über die Suunto-App.
"""

import httpx
from urllib.parse import urlencode
from app.core.config import settings


class SuuntoService:
    AUTH_URL = "https://cloudapi-oauth.suunto.com/oauth/authorize"
    TOKEN_URL = "https://cloudapi-oauth.suunto.com/oauth/token"
    API_BASE = "https://cloudapi.suunto.com/v2"

    def get_auth_url(self, state: str) -> str:
        """Generiert die Suunto OAuth2 Authorization-URL."""
        params = {
            "client_id": settings.suunto_client_id,
            "redirect_uri": settings.suunto_redirect_uri,
            "response_type": "code",
            "scope": "workouts",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access + Refresh Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.suunto_client_id,
                    "client_secret": settings.suunto_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.suunto_redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json()

    async def refresh_token(self, refresh_token: str) -> dict:
        """Erneuert abgelaufenen Access Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.suunto_client_id,
                    "client_secret": settings.suunto_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user(self, access_token: str) -> dict:
        """Lädt Nutzerprofil (Username als Identifier)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/user/profile",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_workouts(
        self, access_token: str, limit: int = 10, since: int | None = None
    ) -> list[dict]:
        """
        Lädt Trainingseinheiten.
        `since` = Unix-Timestamp in Millisekunden (optional, für Delta-Sync).
        """
        params: dict = {"limit": limit}
        if since is not None:
            params["since"] = since

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/workouts",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("payload", [])

    async def get_workout(self, access_token: str, workout_key: str) -> dict:
        """Lädt ein einzelnes Workout inkl. HR-Zonen und Pace."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/workouts/{workout_key}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    def workout_to_training_plan_update(self, workout: dict) -> dict:
        """Konvertiert Suunto-Workout zu TrainingPlan-Update."""
        started_at = workout.get("startTime", "")
        return {
            "date": started_at[:10] if started_at else "",
            "avg_hr": workout.get("heartRateAvg"),
            "duration_min": round(workout.get("totalTime", 0) / 60),
        }

    def workout_to_metric(self, workout: dict) -> dict:
        """Konvertiert Suunto-Workout zu internem Metrik-Format."""
        started_at = workout.get("startTime", "")
        return {
            "duration_min": round(workout.get("totalTime", 0) / 60),
            "distance_m": workout.get("totalDistance"),
            "calories": workout.get("totalCalories"),
            "avg_hr": workout.get("heartRateAvg"),
            "max_hr": workout.get("heartRateMax"),
            "sport": workout.get("activityId", "OTHER"),
            "date": started_at[:10] if started_at else "",
        }
