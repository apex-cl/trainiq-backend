# Design Prompt — TrainIQ App

Kopiere alles zwischen den Strichen in einen neuen Chat mit einem Design-Agent.

---

Du bist ein Senior UI/UX Designer spezialisiert auf datengetriebene Sport-Apps.
Entwirf das komplette Design für **TrainIQ** — ein KI-gestützter persönlicher
Trainings-Coach für Ausdauersportler (Läufer, Radfahrer, Triathleten).

---

## Design-Sprache & Ästhetik

Das Design orientiert sich an diesen 4 Eckpfeilern:

### 1. Typografie — Pixel/Bitmap Display Font für Zahlen
- **Alle numerischen Werte** (HRV, HR, Recovery Score, Schlafdauer, Kalorien)
  werden in einem **Pixel- oder Bitmap-Display-Font** dargestellt —
  wie ein alter LED-Scoreboard oder digitale Uhr. Retro-digital, präzise,
  selbstbewusst. Beispiel-Fonts: "Press Start 2P", "VT323", "Silkscreen",
  "Share Tech Mono", oder "Departure Mono"
- **Labels und Beschriftungen** (z.B. "HRV", "SCHLAF", "ERHOLUNG") in
  kleinen, sehr eng gesperrten ALL-CAPS Light-Sans-Serif. Beispiel: "Inter",
  "DM Sans", "Geist"
- Der Kontrast zwischen den beiden Typografie-Stilen IST das Design.
  Pixel-Font = Daten. Sans-Serif = Kontext.

### 2. Farbe — Monochromatic mit 2 kontrollierten Akzenten
- **Hintergrund:** Sehr dunkles Anthrazit-Grau — NICHT reines Schwarz.
  Empfehlung: `#0D0D0D` oder `#111111` (wirkt hochwertiger als `#000000`)
- **Haupttext & Elemente:** Off-White / Warm-White — `#F0EEE8` oder `#EBEBEB`
  (kein reines Weiß — zu hart)
- **Akzent 1 — Positiv/Gut:** Gedämpftes Amber/Warm-Orange — `#D4863A` oder
  `#C97B2E` (wie der Sonnenuntergang in Bild 3 — warm, nicht grell)
- **Akzent 2 — Negativ/Schlecht:** Gedämpftes Sage-Green oder Coral — nur
  wenn nötig. Kein leuchtendes Rot — eher `#8B4040` (dunkles Rot, subtil)
- **Neutral Grau:** `#2A2A2A` für Cards/Tiles, `#1C1C1C` für Sections
- **Regel:** Maximal 2 Farben gleichzeitig sichtbar. Kein buntes Dashboard.

### 3. Layout — Brutalist Grid, datenorientiert
- Starkes Grid-System. Alles rastet ein. Kein "floating" Design.
- Große Zahlen dominieren den Bildschirm — der Recovery Score soll
  brutal groß und zentral sein, wie eine Uhr.
- **Whitespace ist Inhalt** — Abstände sind großzügig und konsistent (8px Grid)
- Karten/Tiles haben harte, klare Ränder — subtiler Border `#2A2A2A`,
  kein abgerundetes Plastik-Design (max border-radius: 6px)
- Dünne horizontale Trennlinien (1px, `#2A2A2A`) statt Schatten

### 4. Icons & Illustrationen — Line-Art, industriell
- Alle Icons in dünnem, gleichmäßigem Strich (1.5px stroke, kein Fill)
- Sport-Icons (Laufen, Radfahren, Schwimmen) als reduzierte Line-Art
- Keine bunten Icon-Sets. Kein Material Design. Kein iOS-Stil.
- Thin Donut-Charts für Makros, dünne Linien-Charts für Trends
- Balken-Charts für Schlafphasen als sehr schmale vertikale Streifen

---

## Seiten & Komponenten

### ONBOARDING (3 Schritte)

**Schritt 1 — Sport wählen:**
- Schwarzer Hintergrund, App-Name "TRAINIQ" in großem Pixel-Font oben
- 4 große quadratische Tiles in einem 2x2 Grid:
  `[LAUFEN]` `[RADFAHREN]` `[SCHWIMMEN]` `[TRIATHLON]`
- Jedes Tile: Line-Art Sport-Icon + All-Caps Label darunter
- Ausgewählt = Off-White Border + Hintergrund leicht heller (`#1C1C1C`)
- Mehrfachauswahl möglich

**Schritt 2 — Ziel definieren:**
- Coach schreibt in Pixel-Font: `> DEIN ZIEL:`
- Darunter ein Freitext-Input (Terminal-ähnlich, Cursor blinkt wie CLI)
- Zieldatum Picker: Monatsauswahl als horizontale Scroll-Liste

**Schritt 3 — Uhr verbinden:**
- Große Provider-Logos (Garmin, Apple, Strava, Polar) als quadratische Tiles
- Unten: "Ohne Uhr starten" als Ghost-Button (nur Text, kein Background)

---

### DASHBOARD (Hauptseite)

**Oberer Bereich — Recovery Score:**
```
  ┌─────────────────────────────────┐
  │  ERHOLUNG HEUTE    [17. März]   │
  │                                 │
  │        ██  ██  ██               │
  │        ██  ██  ██               │
  │         7  8     (Pixel-Font)   │
  │              ─────              │
  │         BEREIT ZU TRAINIEREN    │
  └─────────────────────────────────┘
```
- Der Score (z.B. "78") in riesigem Pixel-Font — mindestens 72px
- Darunter in kleinem All-Caps: Status-Text ("BEREIT" / "VORSICHT" / "RUHEN")
- Farbe des Scores: Amber (gut) / Neutral (mittel) / Dunkles Rot (schlecht)

**Metriken-Row (3 Tiles horizontal):**
```
  [  HRV  ] [SCHLAF] [STRESS]
  [  ██   ] [ ██   ] [  ██  ]
  [  42ms ] [7.2h  ] [  31  ]
```
- Jedes Tile: kleines Label oben (All-Caps, 10px), große Zahl (Pixel-Font, 28px)
- Pfeil-Indikator: ▲ (besser als gestern) / ▼ (schlechter) in Amber/DarkRed

**Heutiger Trainingsplan (große Karte):**
```
  ┌─────────────────────────────────┐
  │  HEUTE                          │
  │                                 │
  │  —— [Line-Art Lauf-Icon] ——     │
  │                                 │
  │  EASY RUN          45 MIN       │
  │  ZONE 2         140-155 BPM     │
  │                                 │
  │  [DETAILS ANZEIGEN ───────>]    │
  └─────────────────────────────────┘
```

**Ernährungs-Schnellansicht:**
- 3 dünne horizontale Balken (Protein / Carbs / Fett)
- Links: Label. Mitte: dünner Fortschrittsbalken. Rechts: Wert in Pixel-Font.
- Fehlende Nährstoffe: kleines `!` Icon in Amber

**Coach CTA:**
- Volle Breite, schwarzer Button mit Off-White Text
- Text: `> COACH FRAGEN` — das `>` in Amber, Rest in Off-White

---

### CHAT — KI-Coach

**Layout:**
- Hintergrund: `#0D0D0D`
- Coach-Nachrichten: Links, kleines Coach-Icon (quadratisch, Line-Art)
- User-Nachrichten: Rechts, kein Avatar

**Coach-Nachricht Design:**
```
  [C]  ┌──────────────────────────┐
       │ Deine HRV ist heute      │
       │ ██ 34ms ██               │
       │ Das ist unter deinem     │
       │ Durchschnitt von 42ms.   │
       │ Ich empfehle: Ruhetag.   │
       └──────────────────────────┘
       10:34
```
- Zahlen IN der Coach-Nachricht: Pixel-Font, Amber-Farbe — visuell hervorgehoben
- Karten direkt im Chat (z.B. Mini HRV-Chart, Trainingsvorschlag als Tile)

**Daten-Karte im Chat:**
```
  ┌──────────────────────────────────┐
  │  HRV VERLAUF — 7 TAGE           │
  │                                  │
  │   ▁▂▃▃▅▄▂  (dünne Balken)       │
  │  Mo Di Mi Do Fr Sa So            │
  └──────────────────────────────────┘
```

**Quick-Reply Buttons:**
- Horizontal scrollbar, kleine Tiles: `[Warum?]` `[Plan ändern]` `[Ruhetag]`
- Ghost-Style: nur Border, kein Background

**Input-Bar:**
- Terminal-ähnlich: `> _` als Placeholder (Cursor blinkt)
- Rechts: Foto-Upload Icon (Line-Art Kamera) für Essen

---

### TRAINING — Wochenplan

**7-Tage Header (horizontal scroll):**
```
  Mo   Di   Mi   Do   Fr   Sa   So
  [✓]  [✓]  [─]  [>]  [ ]  [ ]  [ ]
  Run  Bike REST  Run  ?    ?    ?
  45m  60m       30m
```
- Erledigte Tage: kleines `✓` in Amber, leicht ausgegraut
- Heutiger Tag: volle Helligkeit, Amber-Border
- Geplante Tage: Ghost-Style

**Tages-Detail:**
- Große Sport-Icon (Line-Art, ~48px)
- Workout-Name in Pixel-Font
- Detaillierte Beschreibung in kleinem Sans-Serif
- Coach-Begründung als Zitat-Block: `" Deine HRV erlaubt intensives Training "`

---

### ERNÄHRUNG

**Upload-Bereich:**
- Gestrichelter Border-Bereich (dashed, `#2A2A2A`)
- Mittig: Kamera-Icon (Line-Art) + Text `FOTO HINZUFÜGEN`
- Tap → Kamera öffnet sich

**Makro-Übersicht:**
```
  KALORIEN          ████████░░░░  1840 / 2400
  PROTEIN           ████████████  148g ✓
  KOHLENHYDRATE     ██████░░░░░░   94g / 180g
  FETT              █████████░░░   62g / 70g
```
- Dünne Fortschrittsbalken (4px Höhe)
- Zahlen in Pixel-Font
- Fehlende: Orange Punkt ● am Anfang der Zeile

**Mahlzeiten-Liste:**
- Einfache Liste mit Trennlinien
- Uhrzeit (klein, All-Caps) | Mahlzeit-Name | Kalorien (Pixel-Font)

**Coach-Tipp:**
```
  ┌──────────────────────────────────┐
  │  ! COACH TIPP                   │
  │  Du trainierst morgen früh.     │
  │  Iss noch ██ 40g ██ Carbs       │
  │  vor dem Schlafen.              │
  └──────────────────────────────────┘
```

---

### METRIKEN — Charts

**HRV Trend (14 Tage):**
- Dünne Linie (`1.5px`), Off-White
- Baseline-Average als gestrichelte Linie in Amber
- X-Achse: kleine Datums-Labels
- Y-Achse: Pixel-Font Zahlen

**Schlaf-Chart:**
- Horizontale gestapelte Balken (sehr dünn, 8px)
- Tiefschlaf: Dunkleres Grau `#3A3A3A`
- REM: Off-White
- Leichtschlaf: Mittleres Grau `#252525`
- Wach: Amber

**Alle Charts:**
- Kein Grid-Overlay (ablenkend)
- Nur Achsen als dünne 1px Linien
- Hover/Tap: kleines Tooltip-Tile erscheint in Pixel-Font

---

### NAVIGATION

**Bottom Tab Bar:**
```
  [◈ HOME] [◫ TRAINING] [◉ CHAT] [◱ ERNÄHR.] [◳ PROFIL]
```
- Icons: dünne Line-Art, 20px
- Aktiver Tab: Amber-Unterstrich (2px), Icon-Farbe Off-White
- Inaktiv: `#555555`
- Kein Background-Highlight — nur die Linie zeigt aktiven State

---

## Technische Anforderungen

- **Framework:** Next.js 14 mit Tailwind CSS
- **UI-Bibliothek:** shadcn/ui als Basis (stark angepasst)
- **Pixel-Font einbinden:** Google Fonts — "VT323" oder "Share Tech Mono"
- **Charts:** Recharts (stark gestylert) oder Victory Native
- **Animationen:** Framer Motion — nur subtile Übergänge (kein Bounce, kein Glow)
  - Zahlen: Count-up Animation beim Laden
  - Seiten: Fade + leichter Slide (200ms, ease-out)
  - Score: Langsames Einblenden der großen Zahl

---

## Was NICHT ins Design soll

- Kein Gradient-Hintergrund (außer als ganz subtiler Noise-Texture)
- Keine runden Bubble-Buttons
- Keine bunten Icon-Hintergründe
- Kein Material Design oder iOS-Kopie
- Kein "Gamification" Design (Badges, Sterne, Konfetti)
- Kein übermäßiges Animieren
- Kein reines Schwarz (`#000000`) oder reines Weiß (`#FFFFFF`)

---

## Ausgabe erwünscht

1. Für jede Seite: vollständige Tailwind-CSS Klassen der Hauptkomponenten
2. Farbpalette als Tailwind-Config (`tailwind.config.js` Erweiterung)
3. Typography-System (welcher Font wo, welche Größe, welches Gewicht)
4. Komponenten-Hierarchie (welche shadcn/ui Komponenten als Basis)
5. Beschreibung der wichtigsten Micro-Interaktionen
6. Vorschlag für Custom CSS für den Pixel-Font in Tailwind
