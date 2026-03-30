import pytest
from app.services.recovery_scorer import RecoveryScorer


def test_perfect_recovery():
    scorer = RecoveryScorer()
    result = scorer.calculate_recovery_score(
        {
            "hrv": 65.0,
            "sleep_duration_min": 480,
            "stress_score": 20.0,
            "resting_hr": 52,
        }
    )
    assert result["score"] >= 70
    assert result["label"] in ["BEREIT"]


def test_poor_recovery():
    scorer = RecoveryScorer()
    result = scorer.calculate_recovery_score(
        {
            "hrv": 18.0,
            "sleep_duration_min": 240,
            "stress_score": 80.0,
            "resting_hr": 85,
        }
    )
    assert result["score"] <= 60
    assert result["label"] in ["VORSICHT", "RUHEN"]


def test_missing_data_defaults():
    scorer = RecoveryScorer()
    result = scorer.calculate_recovery_score(
        {
            "hrv": None,
            "sleep_duration_min": None,
            "stress_score": None,
            "resting_hr": None,
        }
    )
    assert 0 <= result["score"] <= 100


def test_score_weights_hrv_impact():
    scorer = RecoveryScorer()
    good_hrv = scorer.calculate_recovery_score(
        {"hrv": 70, "sleep_duration_min": 420, "stress_score": 30, "resting_hr": 55}
    )
    bad_hrv = scorer.calculate_recovery_score(
        {"hrv": 15, "sleep_duration_min": 420, "stress_score": 30, "resting_hr": 55}
    )
    assert good_hrv["score"] > bad_hrv["score"] + 15


def test_sleep_impact():
    scorer = RecoveryScorer()
    good_sleep = scorer.calculate_recovery_score(
        {"hrv": 40, "sleep_duration_min": 480, "stress_score": 40, "resting_hr": 65}
    )
    bad_sleep = scorer.calculate_recovery_score(
        {"hrv": 40, "sleep_duration_min": 180, "stress_score": 40, "resting_hr": 65}
    )
    assert good_sleep["score"] > bad_sleep["score"]


def test_stress_impact():
    scorer = RecoveryScorer()
    low_stress = scorer.calculate_recovery_score(
        {"hrv": 40, "sleep_duration_min": 420, "stress_score": 10, "resting_hr": 65}
    )
    high_stress = scorer.calculate_recovery_score(
        {"hrv": 40, "sleep_duration_min": 420, "stress_score": 90, "resting_hr": 65}
    )
    assert low_stress["score"] > high_stress["score"]


def test_resting_hr_impact():
    scorer = RecoveryScorer()
    low_hr = scorer.calculate_recovery_score(
        {"hrv": 40, "sleep_duration_min": 420, "stress_score": 40, "resting_hr": 50}
    )
    high_hr = scorer.calculate_recovery_score(
        {"hrv": 40, "sleep_duration_min": 420, "stress_score": 40, "resting_hr": 85}
    )
    assert low_hr["score"] > high_hr["score"]


def test_score_bounds():
    scorer = RecoveryScorer()
    extreme = scorer.calculate_recovery_score(
        {"hrv": 0, "sleep_duration_min": 0, "stress_score": 100, "resting_hr": 200}
    )
    assert 0 <= extreme["score"] <= 100


def test_components_present():
    scorer = RecoveryScorer()
    result = scorer.calculate_recovery_score(
        {"hrv": 45, "sleep_duration_min": 450, "stress_score": 35, "resting_hr": 62}
    )
    assert "hrv_component" in result
    assert "sleep_component" in result
    assert "stress_component" in result
    assert "hr_component" in result


def test_custom_baseline():
    scorer = RecoveryScorer()
    custom_baseline = {
        "hrv": 50.0,
        "sleep_duration_min": 480.0,
        "stress_score": 30.0,
        "resting_hr": 55.0,
        "spo2": 98.0,
    }
    result = scorer.calculate_recovery_score(
        {
            "hrv": 50,
            "sleep_duration_min": 480,
            "stress_score": 30,
            "resting_hr": 55,
            "spo2": 98,
        },
        user_baseline=custom_baseline,
    )
    assert 0 <= result["score"] <= 100


def test_spo2_component():
    scorer = RecoveryScorer()
    high_spo2 = scorer.calculate_recovery_score(
        {
            "hrv": 40,
            "sleep_duration_min": 420,
            "stress_score": 40,
            "resting_hr": 65,
            "spo2": 99,
        }
    )
    low_spo2 = scorer.calculate_recovery_score(
        {
            "hrv": 40,
            "sleep_duration_min": 420,
            "stress_score": 40,
            "resting_hr": 65,
            "spo2": 92,
        }
    )
    assert "spo2_component" in high_spo2
    assert high_spo2["spo2_component"] > low_spo2["spo2_component"]


def test_sleep_stages_quality():
    scorer = RecoveryScorer()
    good_stages = {
        "total": 480,
        "deep": 100,
        "rem": 120,
        "light": 200,
        "awake": 60,
    }
    poor_stages = {
        "total": 480,
        "deep": 20,
        "rem": 30,
        "light": 380,
        "awake": 50,
    }
    result_good = scorer.calculate_recovery_score(
        {
            "hrv": 40,
            "sleep_duration_min": 480,
            "stress_score": 40,
            "resting_hr": 65,
            "sleep_stages": good_stages,
        }
    )
    result_poor = scorer.calculate_recovery_score(
        {
            "hrv": 40,
            "sleep_duration_min": 480,
            "stress_score": 40,
            "resting_hr": 65,
            "sleep_stages": poor_stages,
        }
    )
    assert result_good["sleep_component"] > result_poor["sleep_component"]


def test_baseline_with_spo2():
    scorer = RecoveryScorer()
    metrics = [
        {
            "hrv": 45,
            "sleep_duration_min": 420,
            "stress_score": 35,
            "resting_hr": 62,
            "spo2": 98,
        },
        {
            "hrv": 47,
            "sleep_duration_min": 430,
            "stress_score": 33,
            "resting_hr": 60,
            "spo2": 97,
        },
    ]
    baseline = RecoveryScorer.compute_baseline(metrics)
    assert "spo2" in baseline
    assert baseline["spo2"] == 97.5
