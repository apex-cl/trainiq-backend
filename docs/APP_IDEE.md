# Training Coach App — Idee & Konzept

## Vision

Eine KI-gestützte Trainings-App die einen persönlichen Coach ersetzt. Die App sammelt automatisch Daten von der Smartwatch, analysiert Ernährung, Schlaf und Körperwerte — und plant täglich das Training für den nächsten Tag. Der Coach ist realistisch und sagt dem User die Wahrheit, auch wenn die Ziele nicht erreichbar sind.

**Kernproblem das gelöst wird:**
- Garmin/Whoop Recovery-Vorhersagen sind ungenau (nur HR/HRV, keine Ernährung/Schlaf/Subjektives)
- Echter Personal Coach ist teuer und nicht für jeden zugänglich
- Trainingsvorschläge von Geräten ignorieren den ganzen Menschen

**Wissenschaftliche Grundlage:**
Basierend auf dem Paper *"Multifaktorielle Ansätze zur Optimierung der Trainingssteuerung im Ausdauersport"* — multifaktorielle Modelle (HRV + Schlaf + Ernährung + subjektives Wohlbefinden) verbessern die Erholungsvorhersage um 40-50% gegenüber reinen HR-Systemen.

---

## Zielgruppe

- Hobby- bis Semi-Profi-Athleten
- Läufer, Radfahrer, Schwimmer, Triathleten
- Menschen die keinen persönlichen Coach leisten können oder wollen
- Nutzer von Garmin, Apple Watch, Polar, Whoop und anderen Wearables

---

## Dateneingabe & Quellen

### 1. Smartwatch (automatisch alle 4 Stunden)
- Herzfrequenz (HR) & Herzratenvariabilität (HRV)
- Schlafqualität, Schlafdauer, Schlafphasen
- Stresslevel
- Aktivitätsdaten (Steps, Kalorien, Trainingssessions)
- Körpertemperatur (wenn verfügbar)
- SpO2 (wenn verfügbar)

**Unterstützte Plattformen:**
- Garmin Connect API
- Apple HealthKit
- Google Fit
- Polar Flow
- Whoop API
- Strava (Trainingsdaten)

### 2. Ernährung (User-Upload)
- **Foto-Upload** → KI erkennt Mahlzeit → Nährwerte werden extrahiert
- **Barcode-Scanner** für verpackte Produkte
- **Manuelle Eingabe** als Fallback

**Was analysiert wird:**
- Makronährstoffe (Kohlenhydrate, Protein, Fett)
- Mikronährstoffe (Eisen, Magnesium, Vitamin D, etc.)
- Hydrationsstatus
- Mahlzeiten-Timing (besonders rund um Training)
- Nüchterntraining-Erkennung

**Was der Coach zurückgibt:**
- Fehlende Nährstoffe
- Konkrete Essensvorschläge für heute/morgen
- Pre/Post-Workout Ernährungsempfehlungen

### 3. Subjektives Wohlbefinden (täglich via Chat)
- Morgens automatische Push-Nachricht mit 3 kurzen Fragen:
  - "Wie müde fühlst du dich? (1-10)"
  - "Hast du Schmerzen oder Beschwerden?"
  - "Wie ist deine Stimmung heute?"
- Diese Daten sind laut Paper eine **eigenständige Informationsquelle** die Geräte nicht ersetzen können

---

## Der KI-Coach (Herzstück der App)

### Funktionsweise
Ein Chat-basierter Agent der **alles** in der App steuert. Der User kommuniziert natürlich mit ihm — wie mit einem echten Coach.

### Was der Coach kann

**Zielplanung:**
- User gibt Ziel ein: *"Ich will in 6 Monaten einen Halbmarathon unter 2 Stunden laufen"*
- Coach schaut sich aktuelle Werte an (VO2max, Trainingshistorie, Verfügbarkeit)
- Coach antwortet realistisch: *"Basierend auf deinen aktuellen Werten ist das in 6 Monaten machbar wenn du 4x pro Woche trainierst. Schaffen wir das?"*
- Bei unrealistischen Zielen: **harte Wahrheit** — *"Das ist in 6 Wochen nicht möglich, aber in 16 Wochen schon"*

**Tagesplanung:**
- Jeden Abend: Coach analysiert alle Daten und plant das Training für den nächsten Tag
- Push-Nachricht morgens: *"Heute: 45min Easy Run, Zone 2, 140-155bpm"*
- Wenn Werte schlecht: *"Deine HRV ist heute sehr niedrig und du hast schlecht geschlafen. Ich empfehle aktive Erholung statt Intervalltraining"*

**Anpassung bei Unvorhergesehenem:**
- User: *"Ich bin krank"* → Coach passt die komplette Woche an, schützt die Fitness ohne Überbelastung
- User: *"Ich hatte gestern eine stressige Nacht"* → Coach berücksichtigt das automatisch
- Wenn alle Werte passen → Training wie geplant
- Wenn nicht → angepasster Vorschlag oder Ruhetag

**Wöchentliches Review:**
- Jede Woche: Zusammenfassung mit Fortschritt
- Was hat geklappt, was nicht
- Anpassung des Langzeitplans

**Ernährungs-Coaching:**
- Coach sieht Ernährungsdaten und gibt aktive Tipps
- *"Du trainierst diese Woche 3x nüchtern — das bremst deine Erholung. Iss morgen vor dem Training etwas"*

### Sporarten-Support
- Laufen
- Radfahren
- Schwimmen
- Triathlon (alle drei gleichzeitig mit intelligenter Balance)
- Krafttraining
- Weitere können hinzugefügt werden

---

## Entwicklungsstrategie (Schritt für Schritt)

### Phase A — MVP: Coach-Chat + Basis-Daten
1. Chat-Interface mit KI-Coach
2. User gibt Ziele manuell ein
3. Coach erstellt ersten Trainingsplan
4. Einfache manuelle Dateneingabe (Befinden, Schlaf, Training)
5. Tagesplanung und Benachrichtigungen

### Phase B — Watch-Integration
1. Garmin Connect API anbinden
2. Automatisches Datenholen alle 4 Stunden
3. Coach nutzt echte Körperwerte für Entscheidungen
4. Weitere Wearables hinzufügen (Apple, Polar...)

### Phase C — Ernährung
1. Foto-Upload mit KI-Analyse
2. Barcode-Scanner
3. Coach gibt Ernährungsempfehlungen basierend auf Training

### Phase D — Personalisierung & ML
1. Nach 8-12 Wochen: individuelles ML-Modell pro User
2. Coach wird mit der Zeit immer genauer
3. Transparente Kommunikation der Kalibrierungsphase

---

## Wichtige Prinzipien

**Realismus über Motivation:**
Der Coach schmeichelt nicht. Er sagt die Wahrheit basierend auf echten Daten. Wenn jemand übertrainiert, sagt er es. Wenn ein Ziel unrealistisch ist, sagt er es — aber mit einem realistischen Alternativplan.

**Kalibrierungsphase:**
Die ersten 8-12 Wochen lernt der Coach den User kennen. Er erklärt das transparent: *"Meine Empfehlungen werden mit der Zeit besser je mehr ich über dich lerne."*

**Datenprivatsphäre:**
Gesundheitsdaten sind sensibel — klare Datenschutzrichtlinien von Anfang an.

**Niedrige Einstiegshürde:**
Auch ohne Wearable nutzbar — User kann alles manuell eingeben. Wer eine Uhr hat, bekommt mehr Automatisierung.

---

## Vergleich zu bestehenden Lösungen

| Feature | Garmin Coach | TrainingPeaks | Whoop | Diese App |
|---------|-------------|---------------|-------|-----------|
| KI-Chat Coach | Nein | Nein | Nein | Ja |
| Ernährungsintegration | Nein | Nein | Nein | Ja |
| Subjektives Befinden | Nein | Teilweise | Nein | Ja |
| Multi-Sport (Triathlon) | Teilweise | Ja | Nein | Ja |
| Personalisiertes ML | Nein | Nein | Teilweise | Ja |
| Realistische Zielplanung | Nein | Nein | Nein | Ja |
| Geschätzte Genauigkeit | ~65% | ~55% | ~70% | 85-92% |

---

## Offene Fragen für später

- Welches KI-Modell für den Coach? (Claude API, GPT-4o, eigenes Fine-Tuning?)
- Wie wird Ernährungsfoto-Analyse implementiert? (eigenes Modell oder externe API?)
- Freemium oder Subscription-Modell?
- Wann wird eine eigene ML-Schicht auf die Nutzerdaten trainiert?
- Mehrsprachigkeit von Anfang an?
