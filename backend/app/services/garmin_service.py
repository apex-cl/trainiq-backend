"""
Garmin Connect Integration
Uses garminconnect library (Android SSO) - no enterprise API key needed.
Tokens are stored as JSON: {"_t": <client.dumps()>, "_dn": <display_name>}
for reliable serialization including the display_name needed by stats endpoints.
"""

import asyncio
import json
from typing import Any


class GarminService:

    # ── Serialization helpers ─────────────────────────────────────────────────

    @staticmethod
    def _pack(tokens_str: str, display_name: str) -> str:
        """Wrap raw client.dumps() + display_name into a single storable string."""
        return json.dumps({"_t": tokens_str, "_dn": display_name})

    @staticmethod
    def _unpack(stored: str) -> tuple[str, str | None]:
        """Return (raw_tokens, display_name). Handles both old and new format."""
        try:
            obj = json.loads(stored)
            if isinstance(obj, dict) and "_t" in obj:
                return obj["_t"], obj.get("_dn")
        except (json.JSONDecodeError, TypeError):
            pass
        # Legacy format: stored is the raw client.dumps() string
        return stored, None

    @staticmethod
    def _sync_login(email: str, password: str) -> dict:
        from garminconnect import Garmin  # type: ignore
        garmin = Garmin(email, password)
        garmin.login()
        # Use dumps() to get serializable token string
        raw_tokens = garmin.client.dumps()
        display_name = email
        try:
            profile = garmin.get_user_profile()
            display_name = profile.get("displayName") or profile.get("userName") or email
        except Exception:
            pass
        # Also fall back to garmin.display_name if set by login()
        if hasattr(garmin, "display_name") and garmin.display_name:
            display_name = garmin.display_name
        tokens_json = GarminService._pack(raw_tokens, display_name)
        return {"tokens_json": tokens_json, "display_name": display_name}

    async def login(self, email: str, password: str) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_login, email, password)

    @staticmethod
    def _sync_call(tokens_json: str, fn_name: str, *args: Any) -> Any:
        from garminconnect import Garmin  # type: ignore
        raw_tokens, display_name = GarminService._unpack(tokens_json)
        garmin = Garmin()
        # loads() restores OAuth session tokens
        garmin.client.loads(raw_tokens)
        # Restore display_name — required by stats/sleep/summary endpoints
        if display_name:
            garmin.display_name = display_name
        return getattr(garmin, fn_name)(*args)

    async def get_activities_by_date(self, tokens_json: str, start_date: str, end_date: str) -> list:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_call, tokens_json, "get_activities_by_date", start_date, end_date
        )

    async def get_stats(self, tokens_json: str, date: str) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_call, tokens_json, "get_stats", date
        )

    async def get_sleep_data(self, tokens_json: str, date: str) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_call, tokens_json, "get_sleep_data", date
        )

    async def get_activities(self, tokens_json: str, limit: int = 20) -> list:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_call, tokens_json, "get_activities", 0, limit
        )

    async def get_max_metrics(self, tokens_json: str, date: str) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_call, tokens_json, "get_max_metrics", date
        )

    async def get_hrv_data(self, tokens_json: str, date: str) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_call, tokens_json, "get_hrv_data", date
        )

    def parse_hrv(self, data) -> float | None:
        """Extract HRV (lastNightAvg) from get_hrv_data() response."""
        if not isinstance(data, dict):
            return None
        summary = data.get("hrvSummary") or {}
        val = summary.get("lastNightAvg") or summary.get("weeklyAvg")
        if val is not None:
            try:
                v = float(val)
                if 5 <= v <= 200:
                    return round(v, 1)
            except (TypeError, ValueError):
                pass
        return None

    def parse_vo2_max(self, data) -> float | None:
        """Extract VO2 max from get_max_metrics() response."""
        if not isinstance(data, (dict, list)):
            return None
        # get_max_metrics returns a list of records or a dict with allMetrics
        records = data if isinstance(data, list) else data.get("allMetrics", {}).get("metricsMap", {}).get("WELLNESS_VO2_MAX_ME", [])
        if isinstance(records, list):
            for entry in records:
                val = None
                if isinstance(entry, dict):
                    val = (
                        entry.get("value")
                        or entry.get("vo2MaxPreciseValue")
                        or entry.get("generic", {}).get("vo2MaxPreciseValue")
                        or entry.get("generic", {}).get("vo2MaxValue")
                        or entry.get("generic", {}).get("value")
                    )
                if val is not None:
                    try:
                        v = float(val)
                        if 10 <= v <= 90:
                            return round(v, 1)
                    except (TypeError, ValueError):
                        continue
        # Flat dict format
        if isinstance(data, dict):
            for key in ("vo2MaxPreciseValue", "vo2MaxValue", "maxMet", "vo2Max"):
                v = data.get(key)
                if v is not None:
                    try:
                        f = float(v)
                        if 10 <= f <= 90:
                            return round(f, 1)
                    except (TypeError, ValueError):
                        pass
        return None

    def activity_to_training_plan_update(self, activity: dict) -> dict:
        start_time = activity.get("startTimeLocal") or activity.get("startTimeGMT") or ""
        act_date = start_time[:10] if len(start_time) >= 10 else None
        sport_key = (activity.get("activityType") or {}).get("typeKey") or "other"
        avg_hr = activity.get("averageHR")
        return {
            "date": act_date,
            "sport_type": sport_key,
            "duration_min": round((activity.get("duration") or 0) / 60),
            "avg_hr": int(avg_hr) if avg_hr else None,
            "activity_name": activity.get("activityName", ""),
        }

    def parse_daily_summary(self, data: dict) -> dict:
        return {
            "resting_hr": data.get("restingHeartRate") or data.get("restingHeartRateValue"),
            "steps": data.get("totalSteps"),
            "stress_score": data.get("averageStressLevel"),
            "calories": data.get("activeKilocalories"),
            "distance": data.get("totalDistanceMeters"),
            "spo2": data.get("averageSpo2"),
        }

    # keep legacy alias
    def parse_daily_stats(self, data: dict) -> dict:
        return self.parse_daily_summary(data)

    def parse_sleep(self, data: dict) -> dict:
        daily = data.get("dailySleepDTO") or {}
        total_sec = daily.get("sleepTimeSeconds", 0)
        # avgHeartRate in sleep data is the overnight resting HR (more accurate than daytime)
        sleep_avg_hr = daily.get("avgHeartRate") or daily.get("averageSpO2HRSleep")
        return {
            "sleep_duration_min": round(total_sec / 60) if total_sec else None,
            "sleep_avg_hr": int(sleep_avg_hr) if sleep_avg_hr else None,
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
            "sport_type": (activity.get("activityType") or {}).get("typeKey"),
        }
