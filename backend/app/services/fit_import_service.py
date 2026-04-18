"""
FIT / TCX / GPX Datei-Import Service
Ermöglicht den Import von Trainingsdaten aus exportierten Dateien:

  .fit  — Garmin, COROS, Polar, Suunto, Wahoo, Wahoo (binäres ANT+ Format)
  .tcx  — Garmin Training Center XML (universell von vielen Geräten)
  .gpx  — GPS Exchange Format (universell von allen GPS-Geräten)
  .csv  — Zepp/Amazfit Health Export (Strava-CSV-Format)

Kein API-Key nötig — Nutzer exportieren Dateien direkt von ihrer Uhr / App.
"""

import io
import csv
from datetime import date as _date
from typing import Optional


class FitImportService:
    """Import von .fit Binärdateien (Garmin ANT+ Format)."""

    def parse(self, data: bytes) -> list[dict]:
        """
        Parst eine .fit Datei und gibt eine Liste von Aktivitäts-Dicts zurück.
        Benötigt `fitparse` Bibliothek.
        """
        try:
            from fitparse import FitFile  # type: ignore
        except ImportError:
            raise RuntimeError(
                "fitparse Bibliothek nicht installiert. "
                "Bitte `pip install fitparse` ausführen."
            )

        fitfile = FitFile(io.BytesIO(data))
        sessions = []
        for record in fitfile.get_messages("session"):
            fields = {f.name: f.value for f in record}
            start = fields.get("start_time")
            act_date = None
            if start:
                try:
                    act_date = str(start)[:10]
                except Exception:
                    pass

            sport = str(fields.get("sport") or "other").lower()
            total_elapsed = fields.get("total_elapsed_time") or 0
            avg_hr = fields.get("avg_heart_rate")
            total_distance = fields.get("total_distance")
            total_calories = fields.get("total_calories")
            avg_speed = fields.get("enhanced_avg_speed") or fields.get("avg_speed")

            sessions.append(
                {
                    "date": act_date,
                    "sport_type": sport,
                    "duration_min": round(total_elapsed / 60) if total_elapsed else None,
                    "avg_hr": int(avg_hr) if avg_hr else None,
                    "distance": float(total_distance) if total_distance else None,
                    "calories": int(total_calories) if total_calories else None,
                    "avg_speed": float(avg_speed) if avg_speed else None,
                    "source": "fit_file",
                }
            )

        # Wenn keine Session-Messages: Einzel-Record aus lap-Messages zusammenbauen
        if not sessions:
            lap_distance = 0.0
            lap_elapsed = 0.0
            lap_calories = 0
            act_date = None
            sport = "other"
            for record in fitfile.get_messages("lap"):
                fields = {f.name: f.value for f in record}
                if not act_date and fields.get("start_time"):
                    try:
                        act_date = str(fields["start_time"])[:10]
                    except Exception:
                        pass
                lap_elapsed += fields.get("total_elapsed_time") or 0
                lap_distance += fields.get("total_distance") or 0
                lap_calories += fields.get("total_calories") or 0

            if lap_elapsed and act_date:
                sessions.append(
                    {
                        "date": act_date,
                        "sport_type": sport,
                        "duration_min": round(lap_elapsed / 60),
                        "avg_hr": None,
                        "distance": lap_distance or None,
                        "calories": lap_calories or None,
                        "source": "fit_file",
                    }
                )

        return sessions


class TcxImportService:
    """Import von .tcx Training Center XML Dateien."""

    def parse(self, data: bytes) -> list[dict]:
        """Parst eine .tcx Datei."""
        import defusedxml.ElementTree as ET  # type: ignore

        ns = {"ns": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
        try:
            root = ET.fromstring(data)
        except Exception as e:
            raise ValueError(f"TCX-Datei konnte nicht gelesen werden: {e}")

        activities = []
        for activity in root.findall(".//ns:Activity", ns):
            sport = (activity.get("Sport") or "other").lower()
            laps = activity.findall("ns:Lap", ns)
            if not laps:
                continue

            # Datum aus erstem Lap
            start_time_el = laps[0].find("ns:StartTime", ns)
            if start_time_el is None:
                start_time_el = activity.find("ns:Id", ns)

            act_date = None
            if start_time_el is not None and start_time_el.text:
                act_date = start_time_el.text[:10]

            total_time_sec = 0.0
            total_distance_m = 0.0
            total_calories = 0
            avg_hr_values: list[int] = []

            for lap in laps:
                t = lap.find("ns:TotalTimeSeconds", ns)
                d = lap.find("ns:DistanceMeters", ns)
                c = lap.find("ns:Calories", ns)
                hr_el = lap.find("ns:AverageHeartRateBpm/ns:Value", ns)

                if t is not None and t.text:
                    total_time_sec += float(t.text)
                if d is not None and d.text:
                    total_distance_m += float(d.text)
                if c is not None and c.text:
                    total_calories += int(c.text)
                if hr_el is not None and hr_el.text:
                    avg_hr_values.append(int(hr_el.text))

            avg_hr = (
                round(sum(avg_hr_values) / len(avg_hr_values))
                if avg_hr_values
                else None
            )

            activities.append(
                {
                    "date": act_date,
                    "sport_type": sport,
                    "duration_min": round(total_time_sec / 60) if total_time_sec else None,
                    "avg_hr": avg_hr,
                    "distance": total_distance_m or None,
                    "calories": total_calories or None,
                    "source": "tcx_file",
                }
            )

        return activities


class GpxImportService:
    """Import von .gpx GPS Exchange Format Dateien."""

    def parse(self, data: bytes) -> list[dict]:
        """Parst eine .gpx Datei."""
        import defusedxml.ElementTree as ET  # type: ignore

        # GPX 1.1 Namespace
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        try:
            root = ET.fromstring(data)
        except Exception as e:
            raise ValueError(f"GPX-Datei konnte nicht gelesen werden: {e}")

        activities = []
        for trk in root.findall("gpx:trk", ns):
            name_el = trk.find("gpx:name", ns)
            activity_name = name_el.text if name_el is not None else "GPX Activity"

            trksegs = trk.findall("gpx:trkseg", ns)
            if not trksegs:
                continue

            # Zeitpunkte für Dauer-Berechnung
            all_times: list = []
            all_lats: list = []
            all_lons: list = []

            for seg in trksegs:
                for pt in seg.findall("gpx:trkpt", ns):
                    t_el = pt.find("gpx:time", ns)
                    if t_el is not None and t_el.text:
                        all_times.append(t_el.text)
                    lat = pt.get("lat")
                    lon = pt.get("lon")
                    if lat and lon:
                        all_lats.append(float(lat))
                        all_lons.append(float(lon))

            act_date = None
            duration_min = None

            if all_times:
                act_date = all_times[0][:10]
                if len(all_times) >= 2:
                    try:
                        from datetime import datetime, timezone
                        t_start = datetime.fromisoformat(
                            all_times[0].replace("Z", "+00:00")
                        )
                        t_end = datetime.fromisoformat(
                            all_times[-1].replace("Z", "+00:00")
                        )
                        diff_sec = (t_end - t_start).total_seconds()
                        duration_min = round(diff_sec / 60) if diff_sec > 0 else None
                    except Exception:
                        pass

            # Entfernung via Haversine (vereinfacht)
            distance_m: Optional[float] = None
            if len(all_lats) >= 2:
                import math

                total_dist = 0.0
                for i in range(1, len(all_lats)):
                    lat1, lon1 = all_lats[i - 1], all_lons[i - 1]
                    lat2, lon2 = all_lats[i], all_lons[i]
                    R = 6371000
                    phi1, phi2 = math.radians(lat1), math.radians(lat2)
                    dphi = math.radians(lat2 - lat1)
                    dlambda = math.radians(lon2 - lon1)
                    a = (
                        math.sin(dphi / 2) ** 2
                        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
                    )
                    total_dist += R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                distance_m = total_dist if total_dist > 0 else None

            activities.append(
                {
                    "date": act_date,
                    "sport_type": "other",
                    "duration_min": duration_min,
                    "avg_hr": None,
                    "distance": distance_m,
                    "calories": None,
                    "activity_name": activity_name,
                    "source": "gpx_file",
                }
            )

        return activities


class CsvImportService:
    """Import von CSV-Trainingsdaten (z.B. Zepp Health Export)."""

    # Bekannte Spaltennamen für verschiedene Export-Formate
    _DATE_COLS = ("date", "start_time", "starttime", "Date", "Start Time")
    _SPORT_COLS = ("sport", "type", "activity_type", "Sport", "Type")
    _DURATION_COLS = ("duration", "moving_time", "elapsed_time", "Duration", "Moving Time")
    _HR_COLS = ("avg_hr", "average_heartrate", "avg_heart_rate", "Avg HR")
    _DISTANCE_COLS = ("distance", "Distance")
    _CALORIES_COLS = ("calories", "Calories")

    def _find_col(self, row: dict, candidates: tuple) -> Optional[str]:
        for c in candidates:
            if c in row:
                return c
        return None

    def parse(self, data: bytes) -> list[dict]:
        """Parst eine CSV-Datei mit Trainingsdaten."""
        try:
            text = data.decode("utf-8-sig")  # BOM-tolerant
        except UnicodeDecodeError:
            text = data.decode("latin-1")

        reader = csv.DictReader(io.StringIO(text))
        activities = []

        for row in reader:
            date_col = self._find_col(row, self._DATE_COLS)
            sport_col = self._find_col(row, self._SPORT_COLS)
            dur_col = self._find_col(row, self._DURATION_COLS)
            hr_col = self._find_col(row, self._HR_COLS)
            dist_col = self._find_col(row, self._DISTANCE_COLS)
            cal_col = self._find_col(row, self._CALORIES_COLS)

            act_date = None
            if date_col:
                raw = row[date_col].strip()
                if raw:
                    act_date = raw[:10]

            if not act_date:
                continue

            duration_min = None
            if dur_col:
                raw_dur = row[dur_col].strip()
                # Formats: "01:23:45", "83", "83.5"
                if ":" in raw_dur:
                    parts = raw_dur.split(":")
                    try:
                        if len(parts) == 3:
                            duration_min = (
                                int(parts[0]) * 60
                                + int(parts[1])
                                + int(parts[2]) // 60
                            )
                        elif len(parts) == 2:
                            duration_min = int(parts[0]) + int(parts[1]) // 60
                    except ValueError:
                        pass
                elif raw_dur:
                    try:
                        secs = float(raw_dur)
                        duration_min = round(secs / 60) if secs > 600 else round(secs)
                    except ValueError:
                        pass

            avg_hr = None
            if hr_col and row[hr_col].strip():
                try:
                    avg_hr = int(float(row[hr_col].strip()))
                except ValueError:
                    pass

            distance = None
            if dist_col and row[dist_col].strip():
                try:
                    distance = float(row[dist_col].strip())
                except ValueError:
                    pass

            calories = None
            if cal_col and row[cal_col].strip():
                try:
                    calories = int(float(row[cal_col].strip()))
                except ValueError:
                    pass

            sport = "other"
            if sport_col and row[sport_col].strip():
                sport = row[sport_col].strip().lower()

            activities.append(
                {
                    "date": act_date,
                    "sport_type": sport,
                    "duration_min": duration_min,
                    "avg_hr": avg_hr,
                    "distance": distance,
                    "calories": calories,
                    "source": "csv_file",
                }
            )

        return activities
