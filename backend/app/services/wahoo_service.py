"""
Wahoo Fitness API Integration
Docs: https://developer.wahoofitness.com/wahoo-api/
Free OAuth2 API – kompatibel mit ELEMNT-Computern und KICKR-Trainern.
Wahoo-Geräte synchronisieren auch direkt mit Strava.
"""

import httpx
from urllib.parse import urlencode
from app.core.config import settings


class WahooService:
    AUTH_URL = "https://api.wahooligan.com/oauth/authorize"
    TOKEN_URL = "https://api.wahooligan.com/oauth/token"
    API_BASE = "https://api.wahooligan.com/v1"

    def get_auth_url(self, state: str) -> str:
        """Generiert die Wahoo OAuth2 Authorization-URL."""
        params = {
            "client_id": settings.wahoo_client_id,
            "redirect_uri": settings.wahoo_redirect_uri,
            "response_type": "code",
            "scope": "workouts_read user_read",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access + Refresh Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.wahoo_client_id,
                    "client_secret": settings.wahoo_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.wahoo_redirect_uri,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def refresh_token(self, refresh_token: str) -> dict:
        """Erneuert abgelaufenen Access Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.wahoo_client_id,
                    "client_secret": settings.wahoo_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user(self, access_token: str) -> dict:
        """Lädt Nutzerprofil."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/user",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_workouts(
        self, access_token: str, page: int = 1, per_page: int = 10
    ) -> list[dict]:
        """Lädt Trainingseinheiten (Workouts)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/workouts",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"page": page, "per_page": per_page},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("workouts", [])

    async def get_workout(self, access_token: str, workout_id: int) -> dict:
        """Lädt einen einzelnen Workout."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/workouts/{workout_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    def workout_to_metric(self, workout: dict) -> dict:
        """Konvertiert Wahoo-Workout zu internem Metrik-Format."""
        minutes = round(workout.get("minutes", 0))
        return {
            "duration_min": minutes,
            "distance_m": workout.get("distance_accum"),
            "calories": workout.get("calories_accum"),
            "avg_hr": workout.get("heart_rate_avg"),
            "max_hr": workout.get("heart_rate_max"),
            "sport": workout.get("workout_type_family_name", "OTHER"),
            "date": (workout.get("created_at") or "")[:10],
        }

    def workout_to_training_plan_update(self, workout: dict) -> dict:
        """Konvertiert Wahoo-Workout zu TrainingPlan-Update."""
        return {
            "date": (workout.get("created_at") or "")[:10],
            "avg_hr": workout.get("heart_rate_avg"),
            "duration_min": round(workout.get("minutes", 0)),
        }
