"""
WHOOP Developer API Integration
Docs: https://developer.whoop.com/api
Kostenlose OAuth2 API für WHOOP 4.0 und WHOOP MG.
WHOOP liefert Recovery Score, Strain, HRV, Schlaf und Workouts.
Strava-Sync: WHOOP Workouts können automatisch zu Strava exportiert werden.
"""

import httpx
from urllib.parse import urlencode
from app.core.config import settings


class WhoopService:
    AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
    TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
    API_BASE = "https://api.prod.whoop.com/developer/v1"

    # Benötigte Scopes
    SCOPES = [
        "offline",           # Refresh Tokens
        "read:profile",
        "read:recovery",
        "read:cycles",       # Physiologische Zyklen (je ca. 24h)
        "read:workout",
        "read:sleep",
        "read:body_measurement",
    ]

    def get_auth_url(self, state: str) -> str:
        """Generiert die WHOOP OAuth2 Authorization-URL."""
        params = {
            "client_id": settings.whoop_client_id,
            "redirect_uri": settings.whoop_redirect_uri,
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
                    "client_id": settings.whoop_client_id,
                    "client_secret": settings.whoop_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.whoop_redirect_uri,
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
                    "client_id": settings.whoop_client_id,
                    "client_secret": settings.whoop_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_profile(self, access_token: str) -> dict:
        """Lädt Nutzerprofil (user_id, Name, Email)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/user/profile/basic",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_recovery_collection(
        self,
        access_token: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Lädt Recovery-Daten (Recovery Score 0-100, HRV, Resting HR).
        start / end: ISO 8601 Datetime-Strings (z.B. '2026-01-01T00:00:00.000Z').
        """
        params: dict = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/recovery",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            resp.raise_for_status()
            return resp.json().get("records", [])

    async def get_workout_collection(
        self,
        access_token: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Lädt Workout-Daten (Strain Score, HR-Zonen, Sport-Typ)."""
        params: dict = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/workout",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            resp.raise_for_status()
            return resp.json().get("records", [])

    async def get_sleep_collection(
        self,
        access_token: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Lädt Schlafdaten (Schlaf-Performance Score, Stages, SpO2)."""
        params: dict = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/activity/sleep",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            resp.raise_for_status()
            return resp.json().get("records", [])

    async def get_cycle_collection(
        self,
        access_token: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Lädt physiologische Zyklen (Day Strain, Kalorien)."""
        params: dict = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/cycle",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            resp.raise_for_status()
            return resp.json().get("records", [])

    def workout_to_training_plan_update(self, workout: dict) -> dict:
        """Konvertiert WHOOP-Workout zu TrainingPlan-Update."""
        score = workout.get("score", {}) or {}
        start = workout.get("start", "")
        end = workout.get("end", "")
        # Dauer aus Start/End-Timestamps berechnen (ISO 8601)
        duration_min = None
        if start and end:
            import datetime as _dt
            try:
                start_dt = _dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = _dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
                duration_min = round((end_dt - start_dt).total_seconds() / 60)
            except (ValueError, TypeError):
                pass
        return {
            "date": start[:10] if start else "",
            "avg_hr": score.get("average_heart_rate"),
            "duration_min": duration_min,
        }

    def recovery_to_metric(self, recovery: dict) -> dict:
        """Konvertiert WHOOP-Recovery zu internem Metrik-Format (HRV, Resting HR)."""
        score = recovery.get("score", {}) or {}
        cycle_start = recovery.get("cycle_start", "")
        return {
            "date": cycle_start[:10] if cycle_start else "",
            "hrv": score.get("hrv_rmssd_milli"),
            "resting_hr": score.get("resting_heart_rate"),
            "recovery_score": score.get("recovery_score"),
            "spo2": score.get("spo2_percentage"),
        }

    def sleep_to_metric(self, sleep: dict) -> dict:
        """Konvertiert WHOOP-Schlafdaten zu internem Metrik-Format."""
        score = sleep.get("score", {}) or {}
        start = sleep.get("start", "")
        stage_summary = score.get("stage_summary", {}) or {}
        total_light_ms = stage_summary.get("total_light_sleep_time_milli", 0)
        total_slow_ms = stage_summary.get("total_slow_wave_sleep_time_milli", 0)
        total_rem_ms = stage_summary.get("total_rem_sleep_time_milli", 0)
        total_min = round((total_light_ms + total_slow_ms + total_rem_ms) / 60000)
        return {
            "date": start[:10] if start else "",
            "sleep_duration_min": total_min or None,
            "sleep_quality_score": score.get("sleep_performance_percentage"),
            "spo2": score.get("respiratory_rate"),
        }
