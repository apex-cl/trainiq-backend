"""
Garmin Connect Integration
Uses garminconnect library (Android SSO) - no enterprise API key needed.
"""

import asyncio
import os
import tempfile
from typing import Any


class GarminService:

    @staticmethod
    def _sync_login(email: str, password: str) -> dict:
        from garminconnect import Garmin  # type: ignore
        with tempfile.TemporaryDirectory() as token_dir:
            client = Garmin(email, password)
            client.login(token_dir)
            token_file = os.path.join(token_dir, "garmin_tokens.json")
            tokens_json = ""
            if os.path.exists(token_file):
                with open(token_file) as f:
                    tokens_json = f.read()
            display_name = email
            try:
                profile = client.get_user_profile()
                display_name = profile.get("displayName") or profile.get("userName") or email
            except Exception:
                pass
            return {"tokens_json": tokens_json, "display_name": display_name}

    async def login(self, email: str, password: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_login, email, password)

    @staticmethod
    def _sync_with_tokens(tokens_json: str, fetch_fn_name: str, *args: Any) -> Any:
        from garminconnect import Garmin  # type: ignore
        with tempfile.TemporaryDirectory() as token_dir:
            token_file = os.path.join(token_dir, "garmin_tokens.json")
            with open(token_file, "w") as f:
                f.write(tokens_json)
            client = Garmin()
            client.login(token_dir)
            return getattr(client, fetch_fn_name)(*args)

    async def get_activities(self, tokens_json: str, limit: int = 20) -> list:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_with_tokens, tokens_json, "get_activities", 0, limit
        )

    async def get_stats(self, tokens_json: str, date: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_with_tokens, tokens_json, "get_stats", date
        )

    async def get_sleep_data(self, tokens_json: str, date: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_with_tokens, tokens_json, "get_sleep_data", date
        )

    def parse_daily_stats(self, data: dict) -> dict:
        return {
            "resting_hr": data.get("restingHeartRateValue"),
            "steps": data.get("totalSteps"),
            "stress_score": data.get("averageStressLevel"),
            "calories": data.get("activeKilocalories"),
            "distance": data.get("totalDistanceMeters"),
        }

    def parse_sleep(self, data: dict) -> dict:
        daily = data.get("dailySleepDTO") or {}
        total_sec = daily.get("sleepTimeSeconds", 0)
        return {
            "sleep_duration_min": round(total_sec / 60) if total_sec else None,
            "sleep_stages": {
                "total": total_sec,
                "deep": daily.get("deepSleepSeconds", 0),
                "rem": daily.get("remSleepSeconds", 0),
                "light": daily.get("lightSleepSeconds", 0),
            } if total_sec else None,
        }

    def activity_to_metric(self, activity: dict) -> dict:
        return {
            "duration_min": round((activity.get("duration") or 0) / 60),
            "steps": activity.get("steps"),
            "distance": activity.get("distance"),
            "calories": activity.get("calories"),
            "sport_type": activity.get("activityType", {}).get("typeKey"),
        }
