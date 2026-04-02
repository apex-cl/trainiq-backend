"""
Withings Health API Integration
Docs: https://developer.withings.com/api-reference/
Kostenlose OAuth2 API für Withings-Geräte:
  ScanWatch (Horizon, Light, Nova), Steel HR, Move ECG, Body Cardio, Body+, BPM Core usw.
Withings-Uhren synchronisieren auch mit Strava über Health Mate.
"""

import time
import httpx
from urllib.parse import urlencode
from app.core.config import settings


class WithingsService:
    AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
    TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
    API_BASE = "https://wbsapi.withings.net"

    # Benötigte Scopes
    SCOPES = "user.info,user.metrics,user.activity,user.sleepevents"

    def get_auth_url(self, state: str) -> str:
        """Generiert die Withings OAuth2 Authorization-URL."""
        params = {
            "response_type": "code",
            "client_id": settings.withings_client_id,
            "redirect_uri": settings.withings_redirect_uri,
            "scope": self.SCOPES,
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """
        Tauscht Authorization Code gegen Access + Refresh Token.
        Withings verwendet einen non-standard 'action' Parameter.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "action": "requesttoken",
                    "grant_type": "authorization_code",
                    "client_id": settings.withings_client_id,
                    "client_secret": settings.withings_client_secret,
                    "code": code,
                    "redirect_uri": settings.withings_redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            # Withings wraps tokens in data.body
            body = data.get("body", {})
            return {
                "access_token": body.get("access_token", ""),
                "refresh_token": body.get("refresh_token", ""),
                "userid": body.get("userid"),
            }

    async def refresh_token(self, refresh_token: str) -> dict:
        """Erneuert abgelaufenen Access Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "action": "requesttoken",
                    "grant_type": "refresh_token",
                    "client_id": settings.withings_client_id,
                    "client_secret": settings.withings_client_secret,
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            body = data.get("body", {})
            return {
                "access_token": body.get("access_token", ""),
                "refresh_token": body.get("refresh_token", refresh_token),
            }

    async def get_user_info(self, access_token: str) -> dict:
        """Lädt Nutzerprofil (Vorname, Nachname, Geschlecht, Größe)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.API_BASE}/v2/user",
                headers={"Authorization": f"Bearer {access_token}"},
                data={"action": "getdevice"},
            )
            resp.raise_for_status()
            return resp.json().get("body", {})

    async def get_activity(
        self, access_token: str, start_date: str, end_date: str
    ) -> list[dict]:
        """
        Lädt Aktivitätsdaten (Schritte, Kalorien, Distanz, HR-Durchschnitt).
        start_date / end_date: 'YYYY-MM-DD'
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/v2/measure",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "action": "getactivity",
                    "startdateymd": start_date,
                    "enddateymd": end_date,
                    "data_fields": "steps,distance,calories,totalcalories,hr_average,hr_min,hr_max",
                },
            )
            resp.raise_for_status()
            body = resp.json().get("body", {})
            return body.get("activities", [])

    async def get_workouts(
        self, access_token: str, start_unix: int | None = None, end_unix: int | None = None
    ) -> list[dict]:
        """Lädt Workouts (Sport-Sessions) aus Healthmate."""
        params: dict = {"action": "getworkouts"}
        if start_unix is not None:
            params["startdate"] = start_unix
        if end_unix is not None:
            params["enddate"] = end_unix

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/v2/measure",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            resp.raise_for_status()
            body = resp.json().get("body", {})
            return body.get("series", [])

    async def get_sleep(
        self, access_token: str, start_unix: int, end_unix: int
    ) -> dict:
        """Lädt Schlafdaten (Dauer, Tiefschlaf, REM, SpO2)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/v2/sleep",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "action": "getsummary",
                    "startdateymd": _unix_to_date(start_unix),
                    "enddateymd": _unix_to_date(end_unix),
                    "data_fields": "breathing_disturbances_intensity,deepsleepduration,durationtosleep,hr_average,hr_min,hr_max,remsleepduration,rr_average,sleep_score,snoring,snoringepisodecount,total_sleep_time,wakeupcount,waso",
                },
            )
            resp.raise_for_status()
            body = resp.json().get("body", {})
            series = body.get("series", [])
            return series[0] if series else {}

    async def get_heart_rate(
        self, access_token: str, date: str
    ) -> dict:
        """Lädt Herzfrequenz-Messdaten für ein Datum ('YYYY-MM-DD')."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/measure",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "action": "getmeas",
                    "meastype": "11",  # Typ 11 = Herzfrequenz
                    "category": "1",   # 1 = echte Messungen
                    "startdate": _date_to_unix(date),
                    "enddate": _date_to_unix(date) + 86400,
                },
            )
            resp.raise_for_status()
            body = resp.json().get("body", {})
            return body

    def workout_to_training_plan_update(self, workout: dict) -> dict:
        """Konvertiert Withings-Workout zu TrainingPlan-Update."""
        import datetime as dt
        start_unix = workout.get("startdate", 0)
        date_str = dt.datetime.fromtimestamp(start_unix).date().isoformat() if start_unix else ""
        data = workout.get("data", {})
        return {
            "date": date_str,
            "avg_hr": data.get("hr_average"),
            "duration_min": round(workout.get("duration", 0) / 60),
        }

    def activity_to_metric(self, activity: dict) -> dict:
        """Konvertiert Withings-Tageszusammenfassung zu internem Metrik-Format."""
        return {
            "date": activity.get("date", ""),
            "steps": activity.get("steps"),
            "distance_m": activity.get("distance"),
            "calories": activity.get("calories"),
            "avg_hr": activity.get("hr_average"),
        }

    def sleep_to_metric(self, sleep: dict) -> dict:
        """Konvertiert Withings-Schlafdaten zu internem Metrik-Format."""
        data = sleep.get("data", sleep)  # Withings nests data differently per endpoint
        total_sleep_s = data.get("total_sleep_time") or data.get("deepsleepduration", 0)
        return {
            "sleep_duration_min": round(total_sleep_s / 60) if total_sleep_s else None,
            "sleep_quality_score": data.get("sleep_score"),
            "resting_hr": data.get("hr_min"),
        }


def _unix_to_date(unix_ts: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(unix_ts).date().isoformat()


def _date_to_unix(date_str: str) -> int:
    import datetime as dt
    d = dt.date.fromisoformat(date_str)
    return int(dt.datetime(d.year, d.month, d.day).timestamp())
