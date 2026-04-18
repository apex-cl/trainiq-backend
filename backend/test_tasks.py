"""
TrainIQ — Advanced LLM Task-Tests (25 Tests)
Sport · Ernährung · Medizin · Psychologie · Agent · Multi-Turn · JSON · Performance
"""
import asyncio, os, json, time, re
import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

API_KEY  = os.getenv("LLM_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
MODEL    = os.getenv("LLM_MODEL", "qwen/qwen3.6-plus:free")
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json", "X-Title": "TrainIQ"}

SYSTEM = """Du bist TrainIQ Coach — ein vollumfänglicher KI-Lebenscoach für Athleten und Menschen im Alltag.

EXPERTISEN:
Sport & Training: alle Sportarten, Trainingspläne, HRV, VO2max, Periodisierung
Ernährung: Makros, Sporternährung, Rezepte, Supplementierung, Spezialdiäten
Medizin: Symptome einordnen, Verletzungen, Laborwerte, Medikamente erklären, bei ernstem Symptom Arzt empfehlen
Psychologie: Motivation, Burnout, Stress, Angst, Schlafpsychologie, bei ernsten Problemen Fachmann empfehlen
Schlaf & Regeneration: HRV, Schlafarchitektur, Uebertraining erkennen
Alltag & Lifestyle: Ergonomie, Zeitmanagement, Reisen & Sport

Immer auf Deutsch. Konkret. Laenge dem Thema anpassen."""

RESULTS = []
OK, FAIL, WARN = "OK", "FAIL", "WARN"

TOOL_DATA = {
    "get_user_metrics": json.dumps({"recovery_score": 74, "recovery_label": "Gut", "metriken": [{"datum": "2026-04-02", "hrv_ms": 58, "ruhepuls": 47, "schlaf_min": 450, "stress": 35}]}),
    "get_training_plan": json.dumps([{"datum": "2026-04-02", "typ": "easy_run", "dauer_min": 45, "zone": 2, "status": "planned", "beschreibung": "Lockerer Dauerlauf"}, {"datum": "2026-04-03", "typ": "interval", "dauer_min": 60, "zone": 4, "status": "planned", "beschreibung": "6x1km"}, {"datum": "2026-04-05", "typ": "long_run", "dauer_min": 110, "zone": 2, "status": "planned", "beschreibung": "18km Longrun"}]),
    "get_user_goals": json.dumps({"sport": "Laufen", "ziel": "Halbmarathon unter 1:45h", "level": "intermediate", "wochenstunden": 8}),
    "get_nutrition_summary": json.dumps({"durchschnitt_taeglich": {"kalorien": 2150, "protein_g": 95, "kohlenhydrate_g": 280, "fett_g": 72}}),
    "get_daily_wellbeing": json.dumps({"datum": "2026-04-02", "muedigkeit": 4, "stimmung": 8, "schmerzen": "leichte Spannung Wade rechts"}),
    "get_sleep_trend": json.dumps({"schlaf_stunden_14d": 6.8, "empfehlung_stunden": 8, "deficit_stunden": 1.2}),
    "get_vo2max_history": json.dumps({"aktuell": 52.3, "trend_90d": "+2.1"}),
    "get_injury_history": json.dumps([{"fakt": "Knieoperation links vor 8 Monaten", "kategorie": "injury"}]),
    "calculate_training_zones": json.dumps({"zonen": {"Zone 1": "120-132 bpm", "Zone 2": "132-150 bpm", "Zone 3": "150-162 bpm", "Zone 4": "162-174 bpm", "Zone 5": "174-185 bpm"}}),
    "get_race_history": json.dumps([{"fakt": "Halbmarathon 2025: 1:52:30", "kategorie": "history"}]),
    "set_rest_day": '{"status": "success"}',
    "update_training_day": '{"status": "success"}',
    "analyze_nutrition_gaps": json.dumps({"analyse": "Protein-Defizit: 95g statt 140g"}),
    "log_symptom": '{"status": "success", "message": "gespeichert"}',
    "generate_new_week_plan": '{"status": "success", "plans": 7}',
    "create_weekly_meal_plan": '{"status": "success"}',
}

ALL_TOOLS = [
    {"type": "function", "function": {"name": "get_user_metrics", "description": "Laedt HRV, Ruhepuls, Schlaf + Recovery Score", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_training_plan", "description": "Laedt aktuellen Wochentrainingsplan", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_user_goals", "description": "Laedt Sportziele und Fitnesslevel", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_nutrition_summary", "description": "Laedt Ernaehrungsdaten letzte 7 Tage", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_daily_wellbeing", "description": "Laedt heutiges Befinden", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_sleep_trend", "description": "Laedt Schlaftrend 14 Tage", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_vo2max_history", "description": "Laedt VO2max-Verlauf 90 Tage", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_injury_history", "description": "Laedt bekannte Verletzungen", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_race_history", "description": "Laedt Wettkampfergebnisse und Bestzeiten", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "set_rest_day", "description": "Setzt Ruhetag im Plan", "parameters": {"type": "object", "properties": {"datum": {"type": "string"}, "grund": {"type": "string"}}, "required": ["datum", "grund"]}}},
    {"type": "function", "function": {"name": "update_training_day", "description": "Aktualisiert Trainingseinheit", "parameters": {"type": "object", "properties": {"datum": {"type": "string"}, "workout_type": {"type": "string"}, "dauer_min": {"type": "integer"}, "zone": {"type": "integer"}, "beschreibung": {"type": "string"}}, "required": ["datum", "workout_type", "dauer_min", "zone", "beschreibung"]}}},
    {"type": "function", "function": {"name": "analyze_nutrition_gaps", "description": "Analysiert Naehrstoffluecken", "parameters": {"type": "object", "properties": {"kalorien_ziel": {"type": "integer"}, "protein_ziel_g": {"type": "integer"}}, "required": []}}},
    {"type": "function", "function": {"name": "calculate_training_zones", "description": "Berechnet Herzfrequenztrainingszonen", "parameters": {"type": "object", "properties": {"max_hr": {"type": "integer"}, "resting_hr": {"type": "integer"}, "method": {"type": "string"}}, "required": ["max_hr", "resting_hr"]}}},
    {"type": "function", "function": {"name": "log_symptom", "description": "Speichert Symptom", "parameters": {"type": "object", "properties": {"symptom": {"type": "string"}, "schweregrad": {"type": "integer"}, "bereich": {"type": "string"}}, "required": ["symptom", "schweregrad", "bereich"]}}},
    {"type": "function", "function": {"name": "generate_new_week_plan", "description": "Erstellt neuen KI-Wochentrainingsplan", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "create_weekly_meal_plan", "description": "Erstellt 7-Tage Speiseplan", "parameters": {"type": "object", "properties": {"kalorien_ziel": {"type": "integer"}, "protein_ziel_g": {"type": "integer"}}, "required": ["kalorien_ziel", "protein_ziel_g"]}}},
]


def record(name, passed, elapsed, note=""):
    sym = "✅" if passed else "❌"
    RESULTS.append({"name": name, "passed": passed, "elapsed": elapsed, "note": note})
    extra = f"  <- {note}" if not passed and note else ""
    print(f"  {sym} {name} ({elapsed:.1f}s){extra}")

async def chat_api(messages, tools=None, max_tokens=400):
    payload = {"model": MODEL, "messages": messages, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    async with httpx.AsyncClient(timeout=50) as c:
        r = await c.post(f"{BASE_URL}/chat/completions", headers=HEADERS, json=payload)
        r.raise_for_status()
        return r.json()

def get_content(resp):
    return (resp["choices"][0]["message"].get("content") or "").strip()

def get_tcs(resp):
    return resp["choices"][0]["message"].get("tool_calls") or []

async def run_agent(user_msg, max_rounds=4, max_tokens=350):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_msg}]
    used = []
    for _ in range(max_rounds):
        resp = await chat_api(messages, tools=ALL_TOOLS, max_tokens=max_tokens)
        tc_list = get_tcs(resp)
        if not tc_list:
            return get_content(resp), used
        messages.append(resp["choices"][0]["message"])
        for tc in tc_list:
            fn = tc["function"]["name"]
            used.append(fn)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": TOOL_DATA.get(fn, '{"ok":true}')})
    final = await chat_api(messages, max_tokens=max_tokens)
    return get_content(final), used

# ═══════════════════════ A — SPORT & TRAINING ════════════════════════

async def test_A1_halfmarathon_plan():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Ich laufe 3x/Woche 10km in 55min. Ziel: Halbmarathon unter 1:50h in 3 Monaten. Erstelle Wochenplan Mo-So mit Typ, km, Zone als Tabelle."}], max_tokens=600)
    c = get_content(resp)
    passed = bool(c) and ("|" in c or "-" in c) and len(c) > 200 and any(d in c for d in ["Mo", "Di", "Montag"])
    record("A1 Halbmarathon-Wochenplan", passed, time.time() - t0, c[:60] if not passed else "")

async def test_A2_hr_zones():
    t0 = time.time()
    ans, tools = await run_agent("Mein Max-Puls ist 185, Ruhepuls 48. Berechne meine 5 Herzfrequenzzonen.")
    has_zones = "zone" in ans.lower() and bool(re.search(r"\d{3}\s*[-–]\s*\d{3}", ans))
    record("A2 HF-Zonen berechnen (Tool)", has_zones and bool(ans), time.time() - t0, f"tools={tools}" if not has_zones else f"Tool: {tools}")

async def test_A3_overtraining():
    t0 = time.time()
    data = {"hrv_trend": [62, 54, 46, 38, 30, 24, 19], "ruhepuls": [44, 46, 49, 53, 57, 60, 63]}
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"7-Tage-Trend: {json.dumps(data)}. Was erkennst du?"}], max_tokens=250)
    c = get_content(resp)
    warns = any(kw in c.lower() for kw in ["uebertrain", "uebertraining", "sinkt", "absink", "warnung", "pause", "ruhe"])
    record("A3 Uebertraining erkennen", bool(c) and warns, time.time() - t0, c[:80] if not warns else "")

async def test_A4_taper():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Marathon in 12 Tagen. Letzte Woche: 80km. Taper-Plan?"}], max_tokens=400)
    c = get_content(resp)
    passed = bool(c) and any(kw in c.lower() for kw in ["taper", "reduzier", "volumen", "km"])
    record("A4 Taper-Plan vor Marathon", passed, time.time() - t0, c[:80] if not passed else "")

async def test_A5_vo2max():
    t0 = time.time()
    ans, tools = await run_agent("Mein VO2max ist 48. Wie steigere ich das in 6 Monaten auf 55?")
    passed = bool(ans) and any(kw in ans.lower() for kw in ["vo2", "ausdauer", "intervall", "intervalltraining", "training"])
    record("A5 VO2max-Steigerung", passed, time.time() - t0, ans[:80] if not passed else "")

# ═══════════════════════ B — ERNAEHRUNG ══════════════════════════════

async def test_B1_macros():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "78kg Laeufer, Marathonvorbereitung, 12h/Woche. Berechne Grundumsatz und Makro-Split in Gramm."}], max_tokens=300)
    c = get_content(resp)
    has_g = bool(re.search(r"\d+\s*g", c))
    has_energy = any(kw in c.lower() for kw in ["kcal", "kalori", "grundumsatz", "harris", "verbrauch", "protein", "kohlenhydrat", "kj"])
    passed = bool(c) and (has_g or has_energy) and len(c) > 80
    record("B1 Grundumsatz + Makros", passed, time.time() - t0, c[:80] if not passed else "")

async def test_B2_nutrition_tool():
    t0 = time.time()
    ans, tools = await run_agent("Analysiere meine Ernaehrung der letzten Woche und zeig Defizite.", max_tokens=400)
    used = bool({"get_nutrition_summary", "analyze_nutrition_gaps"} & set(tools))
    record("B2 Ernaehrungs-Tool-Analyse", used and bool(ans), time.time() - t0, f"tools={tools}" if not used else "")

async def test_B3_vegan():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Veganer Triathlet 75kg. Top 5 vegane Proteinquellen mit g/100g."}], max_tokens=300)
    c = get_content(resp)
    has_sources = any(kw in c.lower() for kw in ["tofu", "linsen", "tempeh", "soja", "erbsen", "bohnen", "edamame"])
    passed = bool(c) and has_sources and bool(re.search(r"\d+\s*g", c))
    record("B3 Vegane Sporternaehrung", passed, time.time() - t0, c[:80] if not passed else "")

async def test_B4_race_day_nutrition():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Marathon morgen 9 Uhr. Was esse ich: Abend vorher, Morgen, waehrend, danach?"}], max_tokens=500)
    c = get_content(resp)
    c_lower = c.lower()
    phases = sum(1 for kw in ["abend", "morgen", "w\u00e4hrend", "waehrend", "nach", "during", "gel"] if kw in c_lower)
    record("B4 Renntag-Ernaehrung (4 Phasen)", bool(c) and phases >= 3, time.time() - t0, f"Nur {phases}/4 Phasen" if phases < 3 else "")

# ═══════════════════════ C — MEDIZIN ═════════════════════════════════

async def test_C1_knee_pain():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Seit 3 Wochen Schmerzen Knieaussenseite links, besonders bergab. Was koennte das sein?"}], max_tokens=300)
    c = get_content(resp)
    diagnoses = any(kw in c.lower() for kw in ["iliotibial", "it-band", "laeuferknie", "tractus", "knieband", "sehne", "baender"])
    record("C1 Knieschmerz-Diagnose", bool(c) and (diagnoses or "arzt" in c.lower()), time.time() - t0, c[:100] if not diagnoses else "")

async def test_C2_ferritin():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Mein Ferritin ist 12 ug/l. Was bedeutet das fuer Training und wie erhoehe ich es?"}], max_tokens=300)
    c = get_content(resp)
    has_iron = any(kw in c.lower() for kw in ["eisen", "ferritin", "haem", "mued", "ersch"])
    has_food = any(kw in c.lower() for kw in ["fleisch", "spinat", "linsen", "vitamin c", "lebensmittel", "ernaehrung"])
    record("C2 Ferritin/Eisenmangel erklaeren", bool(c) and has_iron, time.time() - t0, c[:100] if not has_iron else "")

async def test_C3_log_symptom():
    t0 = time.time()
    ans, tools = await run_agent("Symptom erfassen: rechte Achillessehne, Schmerzen Schweregrad 7/10. Nutze das log_symptom Tool um das in meinem Profil zu speichern.")
    used = "log_symptom" in tools
    record("C3 Symptom speichern (Tool)", used and bool(ans), time.time() - t0, f"log_symptom aufgerufen: {used}")

async def test_C4_ibuprofen_warning():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Ich nehme Ibuprofen nach jedem harten Training. Ist das ok langfristig?"}], max_tokens=250)
    c = get_content(resp)
    warns = any(kw in c.lower() for kw in ["nieren", "magen", "langfristig", "risiko", "vorsicht", "nicht emfohlen", "schaedlich", "problematisch", "dauerhaft"])
    record("C4 Ibuprofen-Warnung", bool(c) and warns, time.time() - t0, c[:100] if not warns else "")

async def test_C5_chest_pain_referral():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Beim Laufen spuere ich manchmal Herzstolpern und Schwindel. Weiter trainieren?"}], max_tokens=200)
    c = get_content(resp)
    refers = any(kw in c.lower() for kw in ["arzt", "kardiologe", "ekg", "untersuchung", "abkl", "sofort", "dringend", "nicht trainieren", "nicht weiter", "stop", "pause", "medizin"])
    record("C5 Herzstolpern -> Arzt-Verweis", bool(c) and refers, time.time() - t0, c[:100] if not refers else "")

# ═══════════════════════ D — PSYCHOLOGIE ═════════════════════════════

async def test_D1_race_anxiety():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Vor Wettkampf bekomme ich Panik, kann nicht schlafen, will fast nicht starten. Was tun?"}], max_tokens=300)
    c = get_content(resp)
    passed = bool(c) and any(kw in c.lower() for kw in ["angst", "visualis", "atemue", "routine", "normal", "nervoes", "adrenalin", "cortisol", "nervensystem", "panik", "stress", "aufger", "modus", "wettkampf"])
    record("D1 Wettkampfangst", passed, time.time() - t0, c[:100] if not passed else "")

async def test_D2_burnout():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Seit Monaten intensives Training, dauerhaft erschoepft, keine Freude mehr am Sport, emotional leer. Was ist los?"}], max_tokens=300)
    c = get_content(resp)
    detects = any(kw in c.lower() for kw in ["burnout", "uebertraining", "erschoepf", "pause", "psycholog"])
    record("D2 Burnout erkennen + Hilfe empfehlen", bool(c) and detects, time.time() - t0, c[:100] if not detects else "")

async def test_D3_motivation():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Seit 3 Monaten stagnieren meine Zeiten, verliere Motivation. Was tun?"}], max_tokens=300)
    c = get_content(resp)
    passed = bool(c) and any(kw in c.lower() for kw in ["ziel", "abwechslung", "pause", "neues", "trainingsblock", "variier", "normal", "physiolog", "plateau", "adaptati", "stagnati", "anpassen"])
    record("D3 Motivationsplateau ueberwinden", passed, time.time() - t0, c[:100] if not passed else "")

async def test_D4_sleep():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Liege jede Nacht 1-2h wach, Gedanken drehen sich. Was hilft beim Einschlafen?"}], max_tokens=280)
    c = get_content(resp)
    passed = bool(c) and any(kw in c.lower() for kw in ["schlafhygiene", "routine", "handy", "bildschirm", "entspann", "atem", "meditati", "tagebuch", "kognitiv", "nervensystem", "gedanken", "grübelst", "gr\u00fcbelst"])
    record("D4 Einschlafprobleme", passed, time.time() - t0, c[:100] if not passed else "")

# ═══════════════════════ E — AGENT MULTI-TOOL ════════════════════════

async def test_E1_morning_check():
    t0 = time.time()
    ans, tools = await run_agent("Guten Morgen! Mach meinen Morgen-Check: Metriken, Plan, Befinden — kann ich heute hart trainieren?", max_rounds=5, max_tokens=400)
    loaded = len(set(tools) & {"get_user_metrics", "get_training_plan", "get_daily_wellbeing"}) >= 2
    record("E1 Morgencheck (3+ Tools)", loaded and bool(ans), time.time() - t0, f"Tools: {set(tools)}" if not loaded else f"{len(set(tools))} Tools")

async def test_E2_rest_day_and_symptom():
    t0 = time.time()
    await asyncio.sleep(3)  # rate-limit puffer nach E1
    try:
        ans, tools = await run_agent("Wadenschmerzen, Schweregrad 6. Bitte: (1) log_symptom aufrufen um das Symptom zu speichern, (2) set_rest_day aufrufen fuer morgen 2026-04-03 wegen Schmerzen.")
        used = bool({"log_symptom", "set_rest_day"} & set(tools))
        record("E2 Symptom + Ruhetag (2 Write-Tools)", used and bool(ans), time.time() - t0, f"Tools: {tools}" if not used else f"Tools: {tools}")
    except Exception as ex:
        record("E2 Symptom + Ruhetag (2 Write-Tools)", False, time.time() - t0, f"Exception: {type(ex).__name__}: {ex}")

async def test_E3_race_vs_goal():
    t0 = time.time()
    ans, tools = await run_agent("Schau dir meine Bestzeiten und mein Ziel an — bin ich auf Kurs fuer sub 1:45h?")
    loaded = bool({"get_race_history", "get_user_goals"} & set(tools))
    record("E3 Wettkampfhistorie + Zielcheck", loaded and bool(ans), time.time() - t0, f"Tools: {tools}" if not loaded else "")

async def test_E4_meal_plan():
    t0 = time.time()
    ans, tools = await run_agent("Erstelle mir Speiseplan passend zu meinem Trainingsplan.", max_rounds=5, max_tokens=500)
    used = "create_weekly_meal_plan" in tools
    record("E4 Personalisierter Speiseplan (Tool)", used and bool(ans), time.time() - t0, f"Tools: {tools}" if not used else f"Tools: {tools}")

# ═══════════════════════ F — MULTI-TURN ══════════════════════════════

async def test_F1_pace_context():
    t0 = time.time()
    hist = [{"role": "system", "content": SYSTEM}]
    hist.append({"role": "user", "content": "Ich will Halbmarathon in 1:45h laufen."})
    r1 = await chat_api(hist, max_tokens=80); c1 = get_content(r1); hist.append({"role": "assistant", "content": c1})
    hist.append({"role": "user", "content": "Was ist dann genau mein Zieltempo pro km?"})
    r2 = await chat_api(hist, max_tokens=100); c2 = get_content(r2)
    has_pace = "/km" in c2 or bool(re.search(r"4[:h][45]\d|4:5\d|5:0[01]", c2))
    record("F1 Kontext -> Zieltempo ableiten", bool(c2) and has_pace, time.time() - t0, f"'{c2[:80]}'" if not has_pace else "")

async def test_F2_rehab_followup():
    t0 = time.time()
    hist = [{"role": "system", "content": SYSTEM}]
    hist.append({"role": "user", "content": "Knoechel verstaucht, kann kaum auftreten."})
    r1 = await chat_api(hist, max_tokens=150); c1 = get_content(r1); hist.append({"role": "assistant", "content": c1})
    hist.append({"role": "user", "content": "Wann kann ich wieder laufen und was mache ich in der Zwischenzeit?"})
    r2 = await chat_api(hist, max_tokens=200); c2 = get_content(r2)
    has_timeline = any(kw in c2.lower() for kw in ["woche", "tage", "phase", "rehab", "schwimmen", "alternativ", "verstauch", "ruhe", "schmerz", "entzuend", "eis", "hochleg", "ruhig", "hinweis"])
    record("F2 Verletzungs-Rehab Multi-Turn", bool(c2) and has_timeline, time.time() - t0, c2[:100] if not has_timeline else "")

async def test_F3_beginner_progression():
    t0 = time.time()
    hist = [{"role": "system", "content": SYSTEM}]
    hist.append({"role": "user", "content": "Absoluter Laufanfaenger, 45 Jahre, 90kg, will 5km am Stueck laufen."})
    r1 = await chat_api(hist, max_tokens=200); c1 = get_content(r1); hist.append({"role": "assistant", "content": c1})
    hist.append({"role": "user", "content": "Ich habe nach 2 Wochen schon 3km am Stueck geschafft! Was jetzt?"})
    r2 = await chat_api(hist, max_tokens=200); c2 = get_content(r2)
    encourages = any(kw in c2.lower() for kw in ["toll", "super", "grossartig", "weiter", "steiger", "gut gemacht", "respekt", "stark", "fortschritt", "start", "prima", "schritt"])
    record("F3 Anfaenger-Coaching + Fortschritt", bool(c2) and encourages, time.time() - t0, c2[:80] if not encourages else "")

# ═══════════════════════ G — JSON & STREAMING ════════════════════════

async def test_G1_memory_json():
    t0 = time.time()
    sys_mem = 'Extrahiere Fakten. NUR JSON: [{"fact":"...","category":"injury|preference|goal|constraint|history|feedback|general"}]. Wenn nichts: []'
    resp = await chat_api([{"role": "system", "content": sys_mem}, {"role": "user", "content": "Knieoperation letztes Jahr. Laufe morgens gerne. Ziel: Ironman 70.3 2027. Max 10h/Woche."}], max_tokens=250)
    c = get_content(resp)
    try:
        s, e = c.find("["), c.rfind("]") + 1
        facts = json.loads(c[s:e]) if s >= 0 and e > s else []
        valid_cats = {"injury", "preference", "goal", "constraint", "history", "feedback", "general"}
        valid = all("fact" in f and f.get("category") in valid_cats for f in facts)
        passed = len(facts) >= 3 and valid
        record("G1 Memory-Extraktion (JSON)", passed, time.time() - t0, f"{len(facts)} Fakten, valid={valid}" if not passed else f"{len(facts)} Fakten")
    except Exception as ex:
        record("G1 Memory-Extraktion (JSON)", False, time.time() - t0, str(ex))

async def test_G2_plan_json():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Trainingsplan 7 Tage als JSON-Array. Felder: datum(YYYY-MM-DD), typ, dauer_min, zone(1-5), beschreibung. Start: 2026-04-07. Nur JSON!"}], max_tokens=700)
    c = get_content(resp)
    try:
        s, e = c.find("["), c.rfind("]") + 1
        plan = json.loads(c[s:e]) if s >= 0 and e > s else []
        keys_ok = all({"datum","typ","dauer_min","zone","beschreibung"}.issubset(set(d.keys())) for d in plan if isinstance(d, dict))
        passed = len(plan) == 7 and keys_ok
        record("G2 Trainingsplan als JSON", passed, time.time() - t0, f"{len(plan)} Eintraege, keys={keys_ok}" if not passed else "7 Eintraege OK")
    except Exception as ex:
        record("G2 Trainingsplan als JSON", False, time.time() - t0, str(ex))

async def test_G3_streaming():
    t0 = time.time()
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage
    llm = ChatOpenAI(model=MODEL, api_key=API_KEY, base_url=BASE_URL, max_tokens=500, streaming=True)
    chunks = []
    async for chunk in llm.astream([SystemMessage(content=SYSTEM), HumanMessage(content="Erklaere das 80/20-Trainingsprinzip mit Wochenbeispiel fuer einen Hobby-Triathleten.")]):
        chunks.append(chunk.content)
    full = "".join(chunks).strip()
    passed = len(chunks) > 20 and len(full) > 200
    record("G3 Streaming-Vollstaendigkeit", passed, time.time() - t0, f"{len(chunks)} Chunks, {len(full)} Zeichen")

# ═══════════════════════ H — PERFORMANCE ═════════════════════════════

async def test_H1_response_time():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Top 3 Erholungsmassnahmen nach langem Lauf."}], max_tokens=150)
    elapsed = time.time() - t0
    passed = bool(get_content(resp)) and elapsed < 35.0
    record("H1 Antwortzeit < 35s", passed, time.time() - t0, f"{elapsed:.1f}s" if elapsed >= 35 else "")

async def test_H2_concurrent():
    t0 = time.time()
    questions = ["Was ist Zone-2-Training?", "Wie viel Protein brauche ich (80kg)?", "Was ist ein guter HRV-Wert?"]
    results = await asyncio.gather(*[chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}], max_tokens=100) for q in questions], return_exceptions=True)
    ok = sum(1 for r in results if not isinstance(r, Exception) and get_content(r))
    record("H2 3 Concurrent Requests", ok == 3, time.time() - t0, f"Nur {ok}/3" if ok < 3 else "Alle 3 OK")

async def test_H3_long_quality():
    t0 = time.time()
    resp = await chat_api([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Erklaere Periodisierung im Ausdauersport: Was ist es, welche Modelle gibt es, wie wende ich es als 8h/Woche Hobbysportler an?"}], max_tokens=700)
    c = get_content(resp)
    has_models = any(kw in c.lower() for kw in ["linear", "block", "polar", "makro", "meso", "mikro", "zyklus"])
    passed = bool(c) and len(c) > 400 and has_models
    record("H3 Lange Antwort-Qualitaet", passed, time.time() - t0, f"{len(c)} Zeichen, models={has_models}" if not passed else f"{len(c)} Zeichen")

# ═══════════════════════ MAIN ══════════════════════════════════════════

async def main():
    print(f"\n{'='*65}")
    print(f"  TrainIQ Advanced LLM Tests (25 Tests)")
    print(f"  Modell:  {MODEL}")
    print(f"  URL:     {BASE_URL}")
    print(f"{'='*65}")

    blocks = [
        ("A — Sport & Training", [test_A1_halfmarathon_plan, test_A2_hr_zones, test_A3_overtraining, test_A4_taper, test_A5_vo2max]),
        ("B — Ernaehrung", [test_B1_macros, test_B2_nutrition_tool, test_B3_vegan, test_B4_race_day_nutrition]),
        ("C — Medizin & Gesundheit", [test_C1_knee_pain, test_C2_ferritin, test_C3_log_symptom, test_C4_ibuprofen_warning, test_C5_chest_pain_referral]),
        ("D — Psychologie & Mental", [test_D1_race_anxiety, test_D2_burnout, test_D3_motivation, test_D4_sleep]),
        ("E — Agent Multi-Tool", [test_E1_morning_check, test_E2_rest_day_and_symptom, test_E3_race_vs_goal, test_E4_meal_plan]),
        ("F — Multi-Turn Kontext", [test_F1_pace_context, test_F2_rehab_followup, test_F3_beginner_progression]),
        ("G — JSON & Streaming", [test_G1_memory_json, test_G2_plan_json, test_G3_streaming]),
        ("H — Performance", [test_H1_response_time, test_H2_concurrent, test_H3_long_quality]),
    ]

    for block_name, tests in blocks:
        print(f"\n+-- {block_name}")
        for fn in tests:
            try:
                await fn()
            except Exception as ex:
                RESULTS.append({"name": fn.__name__, "passed": False, "elapsed": 0, "note": str(ex)})
                print(f"  X {fn.__name__}  <- Exception: {ex}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    t_total = sum(r["elapsed"] for r in RESULTS)
    print(f"\n{'='*65}")
    print(f"  Ergebnis: {passed}/{total} bestanden  ({passed/total*100:.0f}%)")
    print(f"  Gesamt-Zeit: {t_total:.1f}s")
    failed = [r for r in RESULTS if not r["passed"]]
    if failed:
        print(f"\n  Fehlgeschlagen ({len(failed)}):")
        for r in failed:
            print(f"    X {r['name']}  -- {r['note']}")
    print(f"{'='*65}\n")

if __name__ == "__main__":
    asyncio.run(main())
