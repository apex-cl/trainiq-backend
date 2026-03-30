"""
Personalized nutrition target calculator.
Estimates daily calorie and macro targets based on sport type,
weekly training hours, and fitness level.
"""


class NutritionTargetCalculator:
    """
    Berechnet tägliche Kalorien- und Makroziele für Ausdauersportler.

    Methodik:
    - Basis-Stoffwechsel: ~2000 kcal (Proxy für 70kg Erwachsenen)
    - Sport-Verbrauch: kcal/Stunde * wöchentliche Stunden / 7 (täglicher Anteil)
    - Protein: abhängig von Fitnesslevel (1.6–2.2g pro kg Körpergewicht)
    - Fett: 25% der Gesamtkalorien
    - Carbs: verbleibende Kalorien
    """

    # Kalorien pro Stunde nach Sportart (Durchschnitt 70kg Athlet)
    KCAL_PER_HOUR: dict[str, float] = {
        "running": 620.0,
        "cycling": 510.0,
        "swimming": 490.0,
        "triathlon": 560.0,
        "Laufen": 620.0,
        "Radfahren": 510.0,
        "Schwimmen": 490.0,
    }
    DEFAULT_KCAL_PER_HOUR = 500.0

    # Protein-Faktor g/kg Körpergewicht nach Fitnesslevel
    PROTEIN_FACTOR: dict[str, float] = {
        "beginner": 1.6,
        "intermediate": 2.0,
        "advanced": 2.2,
    }
    DEFAULT_PROTEIN_FACTOR = 1.8

    # Proxy Körpergewicht (kein echter Input verfügbar)
    PROXY_BODY_WEIGHT_KG = 72.0

    BASE_KCAL = 2000.0

    def calculate(
        self,
        sport: str,
        weekly_hours: int,
        fitness_level: str,
    ) -> dict:
        """
        Berechnet Tagesziele für Kalorien, Protein, Carbs, Fett.

        Returns dict mit:
            calories, protein_g, carbs_g, fat_g, rationale (str)
        """
        kcal_per_hour = self.KCAL_PER_HOUR.get(sport, self.DEFAULT_KCAL_PER_HOUR)
        daily_sport_kcal = (kcal_per_hour * weekly_hours) / 7.0
        total_kcal = self.BASE_KCAL + daily_sport_kcal

        protein_factor = self.PROTEIN_FACTOR.get(
            fitness_level, self.DEFAULT_PROTEIN_FACTOR
        )
        protein_g = protein_factor * self.PROXY_BODY_WEIGHT_KG

        fat_g = (total_kcal * 0.25) / 9.0
        protein_kcal = protein_g * 4.0
        fat_kcal = fat_g * 9.0
        carb_kcal = max(0, total_kcal - protein_kcal - fat_kcal)
        carbs_g = carb_kcal / 4.0

        rationale = (
            f"{sport.capitalize()}, {weekly_hours}h/Woche ({fitness_level}): "
            f"Basis {int(self.BASE_KCAL)} kcal + "
            f"{int(daily_sport_kcal)} kcal Sport = {int(total_kcal)} kcal/Tag"
        )

        return {
            "calories": round(total_kcal),
            "protein_g": round(protein_g, 1),
            "carbs_g": round(carbs_g, 1),
            "fat_g": round(fat_g, 1),
            "sport": sport,
            "weekly_hours": weekly_hours,
            "fitness_level": fitness_level,
            "rationale": rationale,
        }

    def default_targets(self) -> dict:
        """Fallback wenn keine User-Ziele vorhanden."""
        return {
            "calories": 2000,
            "protein_g": 130.0,
            "carbs_g": 230.0,
            "fat_g": 55.6,
            "sport": "allgemein",
            "weekly_hours": 5,
            "fitness_level": "intermediate",
            "rationale": "Standard-Ziele (keine persönlichen Ziele gesetzt)",
        }
