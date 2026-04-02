"""
COROS Open Platform API Integration
Docs: https://open.coros.com/
Kostenlose OAuth2 API für COROS-Uhren:
  VERTIX 2S, APEX 2 Pro, PACE 3, PACE Pro, APEX Pro, DURA usw.
COROS-Uhren synchronisieren direkt mit Strava.
"""

import httpx
from urllib.parse import urlencode
from app.core.config import settings


class CorosService:
    AUTH_URL = "https://open.coros.com/oauth2/authorize"
    TOKEN_URL = "https://open.coros.com/oauth2/accesstoken"
    API_BASE = "https://open.coros.com"

    def get_auth_url(self, state: str) -> str:
        """Generiert die COROS OAuth2 Authorization-URL."""
        params = {
            "client_id": settings.coros_client_id,
            "redirect_uri": settings.coros_redirect_uri,
            "response_type": "code",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Tauscht Authorization Code gegen Access Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_URL,
                json={
                    "client_id": settings.coros_client_id,
                    "client_secret": settings.coros_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.coros_redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            # COROS wraps response in 'data'
            body = data.get("data", data)
            return {
                "access_token": body.get("accessToken", ""),
                "refresh_token": body.get("refreshToken", ""),
                "open_id": body.get("openId", ""),
            }

    async def refresh_token(self, refresh_token: str, open_id: str) -> dict:
        """Erneuert abgelaufenen Access Token."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.API_BASE}/oauth2/refreshAccessToken",
                json={
                    "client_id": settings.coros_client_id,
                    "client_secret": settings.coros_client_secret,
                    "refresh_token": refresh_token,
                    "open_id": open_id,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            body = data.get("data", data)
            return {
                "access_token": body.get("accessToken", ""),
                "refresh_token": body.get("refreshToken", refresh_token),
            }

    async def get_sport_list(
        self,
        access_token: str,
        open_id: str,
        page: int = 1,
        size: int = 10,
    ) -> list[dict]:
        """Lädt Sportaktivitäten (Trainings) des Nutzers."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/v2/coros/sport/list",
                headers={"Authorization": access_token},
                params={
                    "token": access_token,
                    "openId": open_id,
                    "pageNumber": page,
                    "pageSize": size,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            body = data.get("data", {})
            return body.get("dataList", [])

    async def get_sport_detail(
        self, access_token: str, open_id: str, label_id: str, sport_type: int
    ) -> dict:
        """Lädt Details einer einzelnen Aktivität (HR, Pace, Splits)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/v2/coros/sport/detail",
                headers={"Authorization": access_token},
                params={
                    "token": access_token,
                    "openId": open_id,
                    "labelId": label_id,
                    "sportType": sport_type,
                },
            )
            resp.raise_for_status()
            return resp.json().get("data", {})

    def sport_to_training_plan_update(self, sport: dict) -> dict:
        """Konvertiert COROS-Sport zu TrainingPlan-Update."""
        import datetime as dt
        # COROS liefert startTime als Unix-Timestamp (Sekunden)
        start_ts = sport.get("startTime", 0)
        date_str = dt.datetime.fromtimestamp(start_ts).date().isoformat() if start_ts else ""
        return {
            "date": date_str,
            "avg_hr": sport.get("avgHr"),
            "duration_min": round(sport.get("totalTime", 0) / 60),
        }

    def sport_to_metric(self, sport: dict) -> dict:
        """Konvertiert COROS-Sport zu internem Metrik-Format."""
        import datetime as dt
        start_ts = sport.get("startTime", 0)
        date_str = dt.datetime.fromtimestamp(start_ts).date().isoformat() if start_ts else ""
        return {
            "duration_min": round(sport.get("totalTime", 0) / 60),
            "distance_m": sport.get("distance"),
            "calories": sport.get("calorie"),
            "avg_hr": sport.get("avgHr"),
            "max_hr": sport.get("maxHr"),
            "sport": str(sport.get("sportType", "OTHER")),
            "date": date_str,
        }
