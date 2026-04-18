"""Unit tests for NutritionTargetCalculator service."""
import pytest
from app.services.nutrition_targets import NutritionTargetCalculator


@pytest.fixture
def calc():
    return NutritionTargetCalculator()


def test_default_targets(calc):
    """Default targets should be non-zero and include expected keys."""
    result = calc.default_targets()
    assert result["calories"] > 0
    assert result["protein_g"] > 0
    assert result["carbs_g"] > 0
    assert result["fat_g"] > 0
    assert "rationale" in result
    assert result["sport"] == "allgemein"


def test_calculate_runner_beginner(calc):
    result = calc.calculate("running", 5, "beginner")
    assert result["calories"] > 2000  # Should be above base
    assert result["protein_g"] > 0
    assert result["carbs_g"] > 0
    assert result["fat_g"] > 0
    assert result["sport"] == "running"
    assert result["weekly_hours"] == 5
    assert result["fitness_level"] == "beginner"


def test_calculate_runner_advanced_higher_protein(calc):
    """Advanced athletes need more protein than beginners."""
    beginner = calc.calculate("running", 5, "beginner")
    advanced = calc.calculate("running", 5, "advanced")
    assert advanced["protein_g"] > beginner["protein_g"]


def test_calculate_more_hours_more_calories(calc):
    """More training hours should require more calories."""
    low = calc.calculate("running", 2, "intermediate")
    high = calc.calculate("running", 15, "intermediate")
    assert high["calories"] > low["calories"]


def test_calculate_cycling(calc):
    result = calc.calculate("cycling", 8, "intermediate")
    assert result["calories"] > 2000
    assert result["sport"] == "cycling"


def test_calculate_swimming(calc):
    result = calc.calculate("swimming", 6, "advanced")
    assert result["calories"] > 2000
    assert result["sport"] == "swimming"


def test_calculate_triathlon(calc):
    result = calc.calculate("triathlon", 10, "advanced")
    assert result["calories"] > 2500
    assert result["sport"] == "triathlon"


def test_calculate_unknown_sport_uses_default(calc):
    """Unknown sport should fall back to default kcal/hour."""
    result = calc.calculate("crossfit", 5, "intermediate")
    assert result["calories"] > 0  # Should still work


def test_calculate_macros_sum_to_calories(calc):
    """Protein + Carbs + Fat calories should equal total calories (approx)."""
    result = calc.calculate("running", 7, "intermediate")
    protein_kcal = result["protein_g"] * 4
    carbs_kcal = result["carbs_g"] * 4
    fat_kcal = result["fat_g"] * 9
    total_macro_kcal = protein_kcal + carbs_kcal + fat_kcal
    # Should be within 5% of total calories
    assert abs(total_macro_kcal - result["calories"]) / result["calories"] < 0.05


def test_calculate_rationale_present(calc):
    """Rationale string should describe the calculation."""
    result = calc.calculate("cycling", 8, "advanced")
    assert "cycling" in result["rationale"].lower() or "Cycling" in result["rationale"]
    assert "8" in result["rationale"]


def test_default_targets_have_all_keys(calc):
    """Default targets should have the same keys as calculated targets."""
    default = calc.default_targets()
    calculated = calc.calculate("running", 5, "intermediate")
    for key in ["calories", "protein_g", "carbs_g", "fat_g", "rationale"]:
        assert key in default
        assert key in calculated


def test_calculate_fitness_level_affects_protein(calc):
    """Fitness level should monotonically increase protein requirements."""
    beginner = calc.calculate("running", 5, "beginner")
    intermediate = calc.calculate("running", 5, "intermediate")
    advanced = calc.calculate("running", 5, "advanced")
    assert advanced["protein_g"] >= intermediate["protein_g"] >= beginner["protein_g"]
