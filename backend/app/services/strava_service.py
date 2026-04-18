"""
Strava API Integration — Universeller Hub für alle Uhren
Docs: https://developers.strava.com/docs/

Kostenlose OAuth2 API. Strava synchronisiert automatisch mit:
  Garmin, Polar, Wahoo, Fitbit, Suunto, COROS, Zepp/Amazfit,
  Samsung Health, WHOOP, Apple Watch (via HealthFit/WorkOutDoors),
  Withings, Oura, und viele andere.

Einmalige Registrierung unter https://www.strava.com/settings/api
Danach können sich ALLE Nutzer kostenlos über ihr Strava-Konto verbinden.
"""

import httpx
from urllib.parse import urlencode
from app.core.config import settings


class StravaService:
    AUTH_URL = "https://www.strava.com/oauth/authorize"
    TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
    API_BASE = "https://www.strava.com/api/v3"

    # Scopes: Aktivitäten lesen + Profil lesen
    SCOPES = "read,activity:read_all,profile:read_all"

    def get_auth_url(self, state: str) -> str:
        """Generiert die Strava OAuth2 Authorization-URL."""
        params = {
            "client_id": settings.strava_client_id,
            "redirect_uri": settings.strava_redirect_uri,
            "response_type": "code",
            "scope": self.SCOPES,
            "state": state,
            "approval_prompt": "auto",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access + Refresh Token."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                json={
                    "client_id": settings.strava_client_id,
                    "client_secret": settings.strava_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            athlete = data.get("athlete", {})
            return {
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
                "expires_at": data.get("expires_at"),
                "athlete_id": str(athlete.get("id", "")),
                "athlete_name": f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip(),
            }

    async def refresh_token(self, refresh_token: str) -> dict:
        """Erneuert abgelaufenen Access Token."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                json={
                    "client_id": settings.strava_client_id,
                    "client_secret": settings.strava_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_activities(
        self, access_token: str, after_unix: int, limit: int = 200
    ) -> list:
        """Holt Aktivitäten nach einem Unix-Timestamp (max. 200 pro Aufruf)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            all_activities: list = []
            page = 1
            while len(all_activities) < limit:
                per_page = min(100, limit - len(all_activities))
                resp = await client.get(
                    f"{self.API_BASE}/athlete/activities",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "after": after_unix,
                        "per_page": per_page,
                        "page": page,
                    },
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                all_activities.extend(batch)
                if len(batch) < per_page:
                    break
                page += 1
            return all_activities

    def activity_to_training_plan_update(self, activity: dict) -> dict:
        """Konvertiert Strava-Aktivität zu TrainingPlan-Update."""
        start_date = activity.get("start_date_local", "")
        act_date = start_date[:10] if len(start_date) >= 10 else None

        sport_type = (
            activity.get("sport_type") or activity.get("type") or "other"
        ).lower()

        sport_map = {
            "run": "running",
            "virtualrun": "running",
            "trailrun": "running",
            "ride": "cycling",
            "virtualride": "cycling",
            "mountainbikeride": "cycling",
            "ebikeride": "cycling",
            "swim": "swimming",
            "walk": "walking",
            "hike": "hiking",
            "workout": "strength",
            "weighttraining": "strength",
            "yoga": "yoga",
            "crossfit": "strength",
            "rowing": "rowing",
            "skiing": "skiing",
            "snowboard": "skiing",
            "soccer": "team_sport",
            "tennis": "team_sport",
        }
        sport_key = sport_map.get(sport_type, sport_type)
        moving_time_sec = activity.get("moving_time") or 0
        avg_hr = activity.get("average_heartrate")
        return {
            "date": act_date,
            "sport_type": sport_key,
            "duration_min": round(moving_time_sec / 60) if moving_time_sec else None,
            "avg_hr": int(avg_hr) if avg_hr else None,
            "activity_name": activity.get("name", ""),
        }

    def activity_to_metric(self, activity: dict) -> dict:
        """Konvertiert Strava-Aktivität zu HealthMetric-Werten."""
        moving_time_sec = activity.get("moving_time") or 0
        return {
            "duration_min": round(moving_time_sec / 60) if moving_time_sec else None,
            "steps": None,  # Strava hat keine Schrittzählung
            "distance": activity.get("distance"),
            "calories": activity.get("calories"),
            "sport_type": (
                activity.get("sport_type") or activity.get("type") or "other"
            ).lower(),
        }
