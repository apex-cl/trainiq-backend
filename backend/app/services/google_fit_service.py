"""
Google Fit REST API Integration
Docs: https://developers.google.com/fit/rest/
Kostenlose OAuth2 API via Google Cloud Console (kostenlos, nur Registrierung).

Unterstützte Geräte über Google Health Connect / Google Fit:
  - Nothing Watch Pro, CMF Watch Pro 2 (Nothing Technology)
  - OnePlus Watch 2 / 3
  - Fossil Gen 6/7, Skagen Falster
  - Mobvoi TicWatch Pro 5
  - alle Wear OS Uhren ohne eigene API
  - Android-Smartphones (Sensor-Daten)

Einrichtung: https://console.cloud.google.com/ → Fitness API aktivieren
  → OAuth2 Client ID erstellen → google_fit_client_id / google_fit_client_secret
"""

import httpx
from urllib.parse import urlencode
from app.core.config import settings


# Nanosekunden → Millisekunden Hilfsfunktion
def _ns_to_ms(ns: int) -> int:
    return ns // 1_000_000


class GoogleFitService:
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    API_BASE = "https://www.googleapis.com/fitness/v1/users/me"

    # Scopes: https://developers.google.com/fit/datatypes
    SCOPES = [
        "https://www.googleapis.com/auth/fitness.activity.read",
        "https://www.googleapis.com/auth/fitness.heart_rate.read",
        "https://www.googleapis.com/auth/fitness.sleep.read",
        "https://www.googleapis.com/auth/fitness.body.read",
        "https://www.googleapis.com/auth/fitness.oxygen_saturation.read",
    ]

    def get_auth_url(self, state: str) -> str:
        """Generiert die Google OAuth2 Authorization-URL."""
        params = {
            "client_id": settings.google_fit_client_id,
            "redirect_uri": settings.google_fit_redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",   # Notwendig für Refresh Token
            "prompt": "consent",        # Erzwingt Refresh Token bei jedem Auth
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access + Refresh Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.google_fit_client_id,
                    "client_secret": settings.google_fit_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.google_fit_redirect_uri,
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
                    "client_id": settings.google_fit_client_id,
                    "client_secret": settings.google_fit_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_sessions(
        self,
        access_token: str,
        start_time_ms: int,
        end_time_ms: int,
    ) -> list[dict]:
        """
        Lädt Fitness-Sessions (Workouts) aus Google Fit.
        Beinhaltet alle Geräte die über Health Connect synchronisieren.
        start_time_ms / end_time_ms: Unix-Timestamp in Millisekunden.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/sessions",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "startTime": _ms_to_iso(start_time_ms),
                    "endTime": _ms_to_iso(end_time_ms),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("session", [])

    async def get_aggregate(
        self,
        access_token: str,
        start_time_ms: int,
        end_time_ms: int,
        data_type_names: list[str],
        bucket_by_time_days: int = 1,
    ) -> list[dict]:
        """
        Aggregierte Datenpunkte (Schritte, HR, Kalorien, Schlaf) über Zeitraum.
        data_type_names z.B. ['com.google.step_count.delta', 'com.google.heart_rate.bpm']
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.API_BASE}/dataset:aggregate",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "aggregateBy": [
                        {"dataTypeName": name} for name in data_type_names
                    ],
                    "bucketByTime": {"durationMillis": bucket_by_time_days * 86400000},
                    "startTimeMillis": start_time_ms,
                    "endTimeMillis": end_time_ms,
                },
            )
            resp.raise_for_status()
            return resp.json().get("bucket", [])

    async def get_daily_steps(
        self, access_token: str, start_time_ms: int, end_time_ms: int
    ) -> int:
        """Lädt Gesamtschritte für den Zeitraum."""
        buckets = await self.get_aggregate(
            access_token,
            start_time_ms,
            end_time_ms,
            ["com.google.step_count.delta"],
        )
        total = 0
        for bucket in buckets:
            for ds in bucket.get("dataset", []):
                for pt in ds.get("point", []):
                    for val in pt.get("value", []):
                        total += val.get("intVal", 0)
        return total

    async def get_resting_heart_rate(
        self, access_token: str, start_time_ms: int, end_time_ms: int
    ) -> float | None:
        """Lädt Ruhepuls (Durchschnitt) für den Zeitraum."""
        buckets = await self.get_aggregate(
            access_token,
            start_time_ms,
            end_time_ms,
            ["com.google.heart_rate.bpm"],
        )
        values = []
        for bucket in buckets:
            for ds in bucket.get("dataset", []):
                for pt in ds.get("point", []):
                    for val in pt.get("value", []):
                        fp = val.get("fpVal")
                        if fp:
                            values.append(fp)
        return round(sum(values) / len(values)) if values else None

    async def get_sleep_summary(
        self, access_token: str, start_time_ms: int, end_time_ms: int
    ) -> dict:
        """Lädt Schlafdaten aus Google Fit (Health Connect Sleep stages)."""
        buckets = await self.get_aggregate(
            access_token,
            start_time_ms,
            end_time_ms,
            ["com.google.sleep.segment"],
        )
        total_sleep_ms = 0
        for bucket in buckets:
            for ds in bucket.get("dataset", []):
                for pt in ds.get("point", []):
                    # Sleep stage 1=awake, 2=sleep, 3=OOB, 4=light, 5=deep, 6=REM
                    stage = pt.get("value", [{}])[0].get("intVal", 0)
                    if stage in (4, 5, 6):  # light, deep, REM = echter Schlaf
                        start_ns = int(pt.get("startTimeNanos", 0))
                        end_ns = int(pt.get("endTimeNanos", 0))
                        total_sleep_ms += _ns_to_ms(end_ns - start_ns)
        return {
            "sleep_duration_min": round(total_sleep_ms / 60000) if total_sleep_ms else None,
        }

    def session_to_training_plan_update(self, session: dict) -> dict:
        """Konvertiert Google Fit Session zu TrainingPlan-Update."""
        import datetime as dt
        start_ms = int(session.get("startTimeMillis", 0))
        date_str = dt.datetime.fromtimestamp(start_ms / 1000).date().isoformat() if start_ms else ""
        end_ms = int(session.get("endTimeMillis", 0))
        duration_min = round((end_ms - start_ms) / 60000) if end_ms and start_ms else None
        return {
            "date": date_str,
            "avg_hr": None,  # HR kommt aus separatem Aggregate-Call
            "duration_min": duration_min,
        }

    def session_to_metric(self, session: dict) -> dict:
        """Konvertiert Google Fit Session zu internem Metrik-Format."""
        import datetime as dt
        start_ms = int(session.get("startTimeMillis", 0))
        end_ms = int(session.get("endTimeMillis", 0))
        date_str = dt.datetime.fromtimestamp(start_ms / 1000).date().isoformat() if start_ms else ""
        return {
            "duration_min": round((end_ms - start_ms) / 60000) if end_ms and start_ms else None,
            "sport": session.get("activityType", "OTHER"),
            "date": date_str,
        }


def _ms_to_iso(ms: int) -> str:
    """Konvertiert Unix-Timestamp (ms) zu RFC3339-String für Google Fit API."""
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
