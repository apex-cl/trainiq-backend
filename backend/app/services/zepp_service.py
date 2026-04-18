"""
Zepp Health Open Platform API Integration
Docs: https://open-platform.zepp.com/
Kostenlose OAuth2 API für Zepp/Amazfit-Uhren:
  GTR 4/3 Pro, GTS 4/3, T-Rex Ultra/2, Falcon, Cheetah/Pro, Band 7/8, Bip 5 usw.
Amazfit-Uhren synchronisieren über die Zepp App direkt mit Strava.
"""

import hashlib
import time
import httpx
from urllib.parse import urlencode
from app.core.config import settings


class ZeppService:
    AUTH_URL = "https://open-platform.zepp.com/platform/oauth/authorize"
    TOKEN_URL = "https://open-platform.zepp.com/platform/oauth/token"
    API_BASE = "https://open-platform.zepp.com/platform"

    def get_auth_url(self, state: str) -> str:
        """Generiert die Zepp OAuth2 Authorization-URL."""
        params = {
            "app_id": settings.zepp_client_id,
            "redirect_uri": settings.zepp_redirect_uri,
            "response_type": "code",
            "scope": "workout,activity,sleep,heartRate",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def _sign(self, params: dict) -> str:
        """
        Zepp API-Requests werden mit HMAC-ähnlicher Signatur gesichert.
        Sortierte Key=Value-Paare + app_secret, dann MD5.
        """
        sorted_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
        signed_str = f"{sorted_str}&app_secret={settings.zepp_client_secret}"
        return hashlib.md5(signed_str.encode()).hexdigest().upper()

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access + Refresh Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "app_id": settings.zepp_client_id,
                    "app_secret": settings.zepp_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.zepp_redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            body = data.get("data", data)
            return {
                "access_token": body.get("access_token", ""),
                "refresh_token": body.get("refresh_token", ""),
                "open_id": body.get("open_id", ""),
            }

    async def refresh_token(self, refresh_token: str) -> dict:
        """Erneuert abgelaufenen Access Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "app_id": settings.zepp_client_id,
                    "app_secret": settings.zepp_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            body = data.get("data", data)
            return {
                "access_token": body.get("access_token", ""),
                "refresh_token": body.get("refresh_token", refresh_token),
            }

    async def get_workouts(
        self,
        access_token: str,
        open_id: str,
        from_time: int | None = None,
        to_time: int | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Lädt Trainingseinheiten aus der Zepp-App."""
        ts = int(time.time())
        params: dict = {
            "app_id": settings.zepp_client_id,
            "access_token": access_token,
            "open_id": open_id,
            "timestamp": ts,
            "limit": limit,
        }
        if from_time:
            params["from_time"] = from_time
        if to_time:
            params["to_time"] = to_time
        params["sign"] = self._sign(params)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/data/workout/list",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("list", [])

    async def get_sleep(
        self,
        access_token: str,
        open_id: str,
        date_str: str,
    ) -> dict:
        """Lädt Schlafdaten für ein Datum ('YYYY-MM-DD')."""
        ts = int(time.time())
        params = {
            "app_id": settings.zepp_client_id,
            "access_token": access_token,
            "open_id": open_id,
            "timestamp": ts,
            "date": date_str,
        }
        params["sign"] = self._sign(params)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/data/sleep/detail",
                params=params,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})

    async def get_activity(
        self,
        access_token: str,
        open_id: str,
        date_str: str,
    ) -> dict:
        """Lädt Tagesaktivität (Schritte, Kalorien, aktive Zeit)."""
        ts = int(time.time())
        params = {
            "app_id": settings.zepp_client_id,
            "access_token": access_token,
            "open_id": open_id,
            "timestamp": ts,
            "date": date_str,
        }
        params["sign"] = self._sign(params)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/data/activity/detail",
                params=params,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})

    def workout_to_training_plan_update(self, workout: dict) -> dict:
        """Konvertiert Zepp-Workout zu TrainingPlan-Update."""
        import datetime as dt
        start_ts = workout.get("start_time", 0)
        date_str = dt.datetime.fromtimestamp(start_ts).date().isoformat() if start_ts else ""
        return {
            "date": date_str,
            "avg_hr": workout.get("avg_heart_rate"),
            "duration_min": round(workout.get("duration", 0) / 60),
        }

    def workout_to_metric(self, workout: dict) -> dict:
        """Konvertiert Zepp-Workout zu internem Metrik-Format."""
        import datetime as dt
        start_ts = workout.get("start_time", 0)
        date_str = dt.datetime.fromtimestamp(start_ts).date().isoformat() if start_ts else ""
        return {
            "duration_min": round(workout.get("duration", 0) / 60),
            "distance_m": workout.get("distance"),
            "calories": workout.get("calorie"),
            "avg_hr": workout.get("avg_heart_rate"),
            "max_hr": workout.get("max_heart_rate"),
            "sport": workout.get("sport_type", "OTHER"),
            "date": date_str,
        }
