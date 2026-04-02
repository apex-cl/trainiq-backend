"""
Samsung Health Platform API Integration
Docs: https://developer.samsung.com/health/
Kostenlose OAuth2 API (kostenlose Partnerregistrierung erforderlich):
  Galaxy Watch 7, 6, 5, 4, Ultra, Classic, FE, Active 2, Fit3 usw.
Samsung Galaxy Watches (ab Watch 4 Wear OS) synchronisieren auch nativ mit Strava.

Registrierung: https://shealth.samsung.com/ → Developer Console
"""

import httpx
from urllib.parse import urlencode
from app.core.config import settings


class SamsungHealthService:
    # Samsung Account OAuth2
    AUTH_URL = "https://account.samsung.com/accounts/v1/oauth2/authorize"
    TOKEN_URL = "https://account.samsung.com/accounts/v1/oauth2/token"
    API_BASE = "https://shealth.samsung.com/v1"

    # Scopes: https://developer.samsung.com/health/server/scopes.html
    SCOPES = [
        "com.samsung.health.exercise.read",
        "com.samsung.health.sleep.read",
        "com.samsung.health.heart_rate.read",
        "com.samsung.health.step_daily_trend.read",
        "com.samsung.health.oxygen_saturation.read",
        "com.samsung.health.stress.read",
    ]

    def get_auth_url(self, state: str) -> str:
        """Generiert die Samsung Account OAuth2 Authorization-URL."""
        params = {
            "client_id": settings.samsung_health_client_id,
            "redirect_uri": settings.samsung_health_redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access + Refresh Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.samsung_health_client_id,
                    "client_secret": settings.samsung_health_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.samsung_health_redirect_uri,
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
                    "client_id": settings.samsung_health_client_id,
                    "client_secret": settings.samsung_health_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user_profile(self, access_token: str) -> dict:
        """Lädt das Samsung Health Nutzerprofil."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_exercises(
        self,
        access_token: str,
        start_time: int,
        end_time: int,
        limit: int = 10,
    ) -> list[dict]:
        """
        Lädt Sport-Sessions (Workouts) aus Samsung Health.
        start_time / end_time: Unix-Timestamp in Millisekunden.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/users/me/exercise",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "start_time": start_time,
                    "end_time": end_time,
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("exercise", [])

    async def get_sleep(
        self,
        access_token: str,
        start_time: int,
        end_time: int,
    ) -> list[dict]:
        """
        Lädt Schlafdaten aus Samsung Health.
        start_time / end_time: Unix-Timestamp in Millisekunden.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/users/me/sleep",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"start_time": start_time, "end_time": end_time},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("sleep", [])

    async def get_heart_rate(
        self,
        access_token: str,
        start_time: int,
        end_time: int,
    ) -> list[dict]:
        """Lädt Herzfrequenz-Messungen (Resting HR, intraday)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/users/me/heart_rate",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"start_time": start_time, "end_time": end_time},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("heart_rate", [])

    async def get_steps(
        self,
        access_token: str,
        start_time: int,
        end_time: int,
    ) -> list[dict]:
        """Lädt Schrittzähler-Daten."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/users/me/step_daily_trend",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"start_time": start_time, "end_time": end_time},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("step_daily_trend", [])

    def exercise_to_training_plan_update(self, exercise: dict) -> dict:
        """Konvertiert Samsung-Exercise zu TrainingPlan-Update."""
        import datetime as dt
        start_ms = exercise.get("start_time", 0)
        date_str = dt.datetime.fromtimestamp(start_ms / 1000).date().isoformat() if start_ms else ""
        duration_ms = exercise.get("duration", 0)
        return {
            "date": date_str,
            "avg_hr": exercise.get("mean_heart_rate"),
            "duration_min": round(duration_ms / 60000) if duration_ms else None,
        }

    def exercise_to_metric(self, exercise: dict) -> dict:
        """Konvertiert Samsung-Exercise zu internem Metrik-Format."""
        import datetime as dt
        start_ms = exercise.get("start_time", 0)
        date_str = dt.datetime.fromtimestamp(start_ms / 1000).date().isoformat() if start_ms else ""
        duration_ms = exercise.get("duration", 0)
        return {
            "duration_min": round(duration_ms / 60000) if duration_ms else None,
            "distance_m": exercise.get("distance"),
            "calories": exercise.get("calorie"),
            "avg_hr": exercise.get("mean_heart_rate"),
            "max_hr": exercise.get("max_heart_rate"),
            "sport": str(exercise.get("exercise_type", "OTHER")),
            "date": date_str,
        }

    def sleep_to_metric(self, sleep: dict) -> dict:
        """Konvertiert Samsung-Schlafdaten zu internem Metrik-Format."""
        # Samsung liefert Einzel-Stages – total aus Dauer berechnen
        duration_ms = sleep.get("duration", 0)
        return {
            "sleep_duration_min": round(duration_ms / 60000) if duration_ms else None,
            "sleep_quality_score": sleep.get("sleep_score"),
        }
