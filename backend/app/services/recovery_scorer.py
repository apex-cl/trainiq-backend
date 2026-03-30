class RecoveryScorer:
    """Calculates daily recovery score (0-100) based on weighted health metrics.

    Weights:
    - HRV: 30% (strongest predictor)
    - Sleep Duration: 20%
    - Sleep Quality (stages): 10%
    - Stress: 15%
    - Resting HR: 15%
    - SpO2: 10% (blood oxygen)
    """

    DEFAULT_BASELINE = {
        "hrv": 40.0,
        "sleep_duration_min": 420.0,
        "stress_score": 40.0,
        "resting_hr": 65.0,
        "spo2": 98.0,
    }

    @staticmethod
    def compute_baseline(metrics_list: list[dict]) -> dict:
        """Berechnet persönliche Baseline aus den letzten N Messungen."""
        if not metrics_list:
            return RecoveryScorer.DEFAULT_BASELINE

        hrv_vals = [m["hrv"] for m in metrics_list if m.get("hrv")]
        sleep_vals = [
            m["sleep_duration_min"] for m in metrics_list if m.get("sleep_duration_min")
        ]
        stress_vals = [m["stress_score"] for m in metrics_list if m.get("stress_score")]
        hr_vals = [m["resting_hr"] for m in metrics_list if m.get("resting_hr")]
        spo2_vals = [m["spo2"] for m in metrics_list if m.get("spo2")]

        return {
            "hrv": sum(hrv_vals) / len(hrv_vals)
            if hrv_vals
            else RecoveryScorer.DEFAULT_BASELINE["hrv"],
            "sleep_duration_min": sum(sleep_vals) / len(sleep_vals)
            if sleep_vals
            else RecoveryScorer.DEFAULT_BASELINE["sleep_duration_min"],
            "stress_score": sum(stress_vals) / len(stress_vals)
            if stress_vals
            else RecoveryScorer.DEFAULT_BASELINE["stress_score"],
            "resting_hr": sum(hr_vals) / len(hr_vals)
            if hr_vals
            else RecoveryScorer.DEFAULT_BASELINE["resting_hr"],
            "spo2": sum(spo2_vals) / len(spo2_vals)
            if spo2_vals
            else RecoveryScorer.DEFAULT_BASELINE["spo2"],
        }

    @staticmethod
    def _normalize(value: float, baseline: float, weight: float) -> float:
        """Normalize a metric against its baseline and apply weight."""
        if baseline == 0:
            return weight * 50.0
        ratio = value / baseline
        return weight * min(1.0, ratio) * 100.0

    @staticmethod
    def _calculate_sleep_quality_score(sleep_stages: dict | None) -> float:
        """Calculate sleep quality based on sleep stages (REM, Deep, Light)."""
        if not sleep_stages:
            return 0.5

        total = sleep_stages.get("total", 0)
        if total == 0:
            return 0.5

        deep = sleep_stages.get("deep", 0)
        rem = sleep_stages.get("rem", 0)

        deep_ratio = deep / total
        rem_ratio = rem / total

        deep_score = min(deep_ratio / 0.20, 1.0) * 0.5
        rem_score = min(rem_ratio / 0.25, 1.0) * 0.5

        return deep_score + rem_score

    def calculate_recovery_score(
        self, metrics: dict, user_baseline: dict | None = None
    ) -> dict:
        """Calculate recovery score from health metrics dict. Returns dict with score and components."""
        baseline = user_baseline or self.DEFAULT_BASELINE

        hrv = metrics.get("hrv") or baseline["hrv"]
        sleep = metrics.get("sleep_duration_min") or baseline["sleep_duration_min"]
        stress = metrics.get("stress_score") or baseline["stress_score"]
        resting_hr = metrics.get("resting_hr") or baseline["resting_hr"]
        spo2 = metrics.get("spo2") or baseline.get("spo2", 98.0)
        sleep_stages = metrics.get("sleep_stages")

        hrv_component = self._normalize(hrv, baseline["hrv"], 0.30)

        sleep_duration_optimal = 480.0
        sleep_duration_ratio = (
            min(sleep / sleep_duration_optimal, 1.0)
            if sleep_duration_optimal > 0
            else 0.5
        )
        sleep_duration_component = sleep_duration_ratio * 0.20 * 100.0

        sleep_quality_score = self._calculate_sleep_quality_score(sleep_stages)
        sleep_quality_component = sleep_quality_score * 0.10 * 100.0

        sleep_component = sleep_duration_component + sleep_quality_component

        stress_inverted = max(0, 100 - stress)
        stress_baseline_inverted = max(0, 100 - baseline["stress_score"])
        stress_component = self._normalize(
            stress_inverted, stress_baseline_inverted, 0.15
        )

        hr_baseline = baseline["resting_hr"]
        if hr_baseline > 0 and resting_hr > 0:
            hr_component = min(hr_baseline / resting_hr, 1.0) * 0.15 * 100.0
        else:
            hr_component = 0.15 * 50.0

        spo2_baseline = baseline.get("spo2", 98.0)
        if spo2_baseline > 0 and spo2 > 0:
            spo2_component = min(spo2 / spo2_baseline, 1.0) * 0.10 * 100.0
        else:
            spo2_component = 0.10 * 50.0

        score = int(
            min(
                100,
                max(
                    0,
                    hrv_component
                    + sleep_component
                    + stress_component
                    + hr_component
                    + spo2_component,
                ),
            )
        )

        if score >= 70:
            label = "BEREIT"
        elif score >= 40:
            label = "VORSICHT"
        else:
            label = "RUHEN"

        return {
            "score": score,
            "label": label,
            "hrv_component": round(hrv_component, 2),
            "sleep_component": round(sleep_component, 2),
            "stress_component": round(stress_component, 2),
            "hr_component": round(hr_component, 2),
            "spo2_component": round(spo2_component, 2),
        }
