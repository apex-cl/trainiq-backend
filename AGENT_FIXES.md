# TrainIQ Coach — Bugfixes & Vervollständigung: Implementierungsanleitung

> **Für den implementierenden Agent:** Lese JEDE Datei vor der Änderung komplett. Alle Pfade relativ zu `/Users/abu/Projekt/trainiq/`. Implementiere in der angegebenen Reihenfolge.

---

## 0. Übersicht der Probleme

| # | Problem | Datei | Schwere |
|---|---------|-------|---------|
| 1 | Thinking-Tokens `(Denken: ...)` erscheinen im Chat | `coach_agent.py` | 🔴 Kritisch |
| 2 | LangChain streamt Tool-JSON in Chat | `langchain_agent.py` | 🔴 Kritisch |
| 3 | LLM hat keinen Scope — antwortet auf alles | `coach_agent.py`, `langchain_agent.py` | 🔴 Kritisch |
| 4 | 4 verschiedene System-Prompts — inkonsistent | alle services | 🟠 Hoch |
| 5 | Autonomous Monitor hat keinen Cooldown → spammt User | `autonomous_monitor.py` | 🟠 Hoch |
| 6 | Sleep Tips statische Liste statt LLM-personalisiert | `sleep_coach.py` | 🟡 Mittel |
| 7 | Meal Plan ignoriert Trainingsbelastung der Woche | `meal_planner.py` | 🟡 Mittel |
| 8 | Frontend Markdown unlesbar (kein echtes Rendering) | `MessageBubble.tsx` | 🟡 Mittel |
| 9 | useCoach SSE Parser bricht bei Newlines im Text | `useCoach.ts` | 🟡 Mittel |
| 10 | `build_context()` fehlt: Tageszeit, Wochentag, Wearable-Summary | `coach_agent.py` | 🟡 Mittel |

---

## 1. Fix: Thinking-Tokens aus Chat entfernen

### Datei: `backend/app/services/coach_agent.py`

**Problem:** In `_llm_chunks()` werden Reasoning-Tokens des Modells (`delta.reasoning`) als `(Denken: ...)` in den Stream ausgegeben. Das zerstört die Lesbarkeit.

**Lese die Datei. Suche diesen Block (ca. Zeile 315-325):**
```python
content = delta.get("content", "")
reasoning = delta.get("reasoning", "")

if reasoning:
    # Optional: Denken visuell hervorheben
    yield f"(Denken: {reasoning})"
elif content:
    yield content
```

**Ersetze durch:**
```python
content = delta.get("content", "")
# reasoning/thinking tokens werden bewusst ignoriert — nur finaler Content wird gestreamt
if content:
    yield content
```

**Begründung:** Modelle wie Kimi k2, DeepSeek R1 trennen Thinking (`delta.reasoning`) von der Antwort (`delta.content`). Nur `content` ist für den User bestimmt.

---

## 2. Fix: LangChain streamt keine Tool-Internals mehr

### Datei: `backend/app/services/langchain_agent.py`

**Problem:** `astream_events` liefert viele Event-Typen. Aktuell wird nur `on_chat_model_stream` gefiltert, aber LangChain sendet dabei auch Chunks während Tool-Aufrufen, die als JSON/Tool-Namen im Stream landen können.

**Lese die Datei. Suche den `stream()` Methoden-Block mit dem `astream_events` Loop.**

**Ersetze den Event-Loop komplett durch diese verbesserte Version:**

```python
full_response = ""
tool_call_active = False  # Flag: Aktuell läuft ein Tool-Call

try:
    executor = self._build_executor(user_id, db, streaming=True)
    async for event in executor.astream_events(
        {"input": message, "chat_history": chat_history},
        version="v1",
    ):
        event_name = event.get("event", "")

        # Tool-Call Start: Streaming pausieren
        if event_name == "on_tool_start":
            tool_call_active = True
            tool_name = event.get("name", "tool")
            # Kurze Status-Info an User (einmalig, kein Stream-Chunk)
            status_msg = _tool_status_message(tool_name)
            if status_msg:
                full_response += status_msg
                yield f"data: {status_msg}\n\n"
            continue

        # Tool-Call Ende: Streaming wieder freigeben
        if event_name == "on_tool_end":
            tool_call_active = False
            continue

        # Nur finale LLM-Antwort streamen (nicht während Tool-Calls)
        if event_name == "on_chat_model_stream" and not tool_call_active:
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                text = chunk.content
                # Reasoning/Thinking ignorieren (falls als Chunk-Attribut)
                if hasattr(chunk, "additional_kwargs"):
                    reasoning = chunk.additional_kwargs.get("reasoning", "")
                    if reasoning and not text:
                        continue
                full_response += text
                # Newlines in SSE escapen
                safe = text.replace("\n", "\ndata: ")
                yield f"data: {safe}\n\n"

except Exception as e:
    logger.error(f"LangChain stream failed | user={user_id} | error={e}")
    # Fallback auf CoachAgent
    from app.services.coach_agent import CoachAgent
    fallback = CoachAgent()
    async for chunk in fallback.stream(message, user_id, db):
        yield chunk
    return
```

**Füge diese Hilfsfunktion VOR der `LangChainCoachAgent` Klasse ein:**

```python
def _tool_status_message(tool_name: str) -> str:
    """Gibt eine lesbare Status-Nachricht für Tool-Aufrufe zurück."""
    STATUS_MAP = {
        "get_user_metrics": "📊 *Lade deine Gesundheitsmetriken...*\n\n",
        "get_training_plan": "🏃 *Lade deinen Trainingsplan...*\n\n",
        "set_rest_day": "😴 *Setze Ruhetag...*\n\n",
        "update_training_day": "✏️ *Passe Training an...*\n\n",
        "generate_new_week_plan": "📅 *Erstelle neuen Wochenplan...*\n\n",
        "get_nutrition_summary": "🥗 *Lade Ernährungsdaten...*\n\n",
        "create_weekly_meal_plan": "🍳 *Erstelle Wochenspeiseplan mit Rezepten...*\n\n",
        "get_user_goals": "🎯 *Lade deine Ziele...*\n\n",
        "get_daily_wellbeing": "💭 *Lade heutiges Befinden...*\n\n",
        "analyze_nutrition_gaps": "🔍 *Analysiere Nährstofflücken...*\n\n",
    }
    return STATUS_MAP.get(tool_name, "")
```

---

## 3. Fix: Einheitlicher, scopegebundener System Prompt

**Problem:** Es gibt 4 verschiedene System-Prompts (`coach_agent.py`, `langchain_agent.py`, `autonomous_monitor.py`, `sleep_coach.py`). Der LLM hat keine klaren Grenzen und kann über alles reden.

### Neue Datei erstellen: `backend/app/services/coach_prompts.py`

**Erstelle diese neue Datei:**

```python
"""Zentrale Coach-Prompts — Single Source of Truth für alle Coach-Services."""

from datetime import datetime, timezone


def get_base_system_prompt() -> str:
    """
    Basis-System-Prompt für alle Coach-Interaktionen.
    Strict Scope: Nur Training, Ernährung, Schlaf, Gesundheitsmetriken.
    """
    now = datetime.now(timezone.utc)
    weekday_de = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    day_name = weekday_de[now.weekday()]
    hour = now.hour

    if 5 <= hour < 10:
        tageszeit = "Morgen"
    elif 10 <= hour < 17:
        tageszeit = "Nachmittag"
    elif 17 <= hour < 21:
        tageszeit = "Abend"
    else:
        tageszeit = "Nacht"

    return f"""Du bist TrainIQ Coach — ein spezialisierter KI-Assistent ausschließlich für Ausdauersport und Gesundheit.

HEUTE: {day_name}, {tageszeit} (UTC Stunde: {hour})

DEINE 4 EXPERTISEN:
🏃 TRAININGSCOACH — Trainingspläne, Intensitäten, Recovery, Periodisierung
🥗 ERNÄHRUNGSBERATER — Makronährstoffe, Timing, Defizite, Speisepläne mit Rezepten
💤 SCHLAFCOACH — Schlafqualität, HRV-Einfluss, Schlafhygiene, Erholung
🏥 GESUNDHEITSANALYST — HRV, Ruhepuls, Stress, Übertraining erkennen

STRIKTE GRENZEN — NICHT BEANTWORTEN:
- Fragen ohne Bezug zu Sport, Ernährung, Schlaf oder Gesundheitsmetriken
- Allgemeine Wissensfragen (Geschichte, Politik, Technik, etc.)
- Coding-Hilfe, rechtliche Beratung, Finanzberatung
- Bei Off-Topic: Antworte GENAU so: "Als TrainIQ Coach helfe ich dir nur bei Training, Ernährung, Schlaf und Gesundheit. Was kann ich in diesen Bereichen für dich tun?"

DATEN-REGELN:
1. Nutze IMMER die verfügbaren Tools — lade echte Daten, bevor du antwortest
2. Nenne IMMER konkrete Zahlen (nicht "deine HRV ist gut" → "deine HRV ist 42ms, 8% über deinem 7-Tage-Schnitt")
3. Erfinde keine Werte — wenn keine Daten vorhanden: sag es klar
4. HRV < 20% unter Durchschnitt ODER Schlaf < 360min → Ruhetag setzen UND empfehlen

ANTWORT-STIL:
- Deutsch, direkt, konkret
- Max 4 Sätze außer bei Plänen/Rezepten
- {_get_time_specific_behavior(hour)}
- Wechsle Persona automatisch je nach Thema (Trainer/Ernährungsberater/Schlafcoach/Arzt)"""


def _get_time_specific_behavior(hour: int) -> str:
    """Zeitspezifisches Verhalten je nach Tageszeit."""
    if 5 <= hour < 10:
        return "Morgens: Begrüße den User, gib Recovery-Check und Tages-Trainingsempfehlung"
    elif 10 <= hour < 17:
        return "Tagsüber: Fokus auf Training-Fragen, Ernährungs-Tracking, Plan-Anpassungen"
    elif 17 <= hour < 21:
        return "Abends: Fokus auf Post-Training-Recovery, Ernährung, Vorbereitung für morgen"
    else:
        return "Nachts/Spät: Fokus auf Schlaf-Vorbereitung, gib automatisch Schlaftipp"


def get_autonomous_system_prompt() -> str:
    """System-Prompt für autonome Background-Jobs (kein Streaming)."""
    return get_base_system_prompt() + """

AUTONOMER MODUS: Du arbeitest im Hintergrund ohne User-Interaktion.
- Führe Aktionen direkt aus ohne zu fragen
- Sei konservativ: lieber zu wenig ändern als zu viel
- Dokumentiere jede Aktion klar in der Ausgabe"""


def get_detection_prompt(messages_text: str) -> str:
    """Prompt für Conversation-Klassifikation im Autonomous Monitor."""
    return f"""Analysiere diese Chat-Nachrichten eines Ausdauersportlers.

Erkenne NUR eines dieser spezifischen Ereignisse:
- "bad_feeling": Nutzer sagt explizit dass er sich krank/erschöpft/sehr schlecht fühlt
- "skipped_training": Nutzer hat Training definitiv ausgelassen (nicht nur geplant)
- "injury": Nutzer beschreibt eine aktuelle Verletzung (nicht historisch)
- "normal": Keines der obigen Ereignisse klar erkennbar

WICHTIG: Im Zweifel → "normal". Nur bei EINDEUTIGER Aussage handeln.

Antworte NUR als JSON:
{{"event": "bad_feeling"|"skipped_training"|"injury"|"normal", "confidence": "high"|"medium"|"low", "detail": "1 Satz Begründung"}}

Chat (neueste zuerst):
{messages_text}

JSON:"""
```

---

## 4. Fix: `coach_agent.py` — Scope + neuer Context

### Datei: `backend/app/services/coach_agent.py`

**Lese die Datei. Führe diese Änderungen durch:**

### 4a. Import hinzufügen (oben bei den anderen Imports):
```python
from app.services.coach_prompts import get_base_system_prompt
```

### 4b. `SYSTEM_PROMPT` Klassen-Attribut entfernen:
Lösche den kompletten `SYSTEM_PROMPT = """..."""` Block aus der Klasse.

### 4c. In `_llm_chunks()`: System Prompt dynamisch laden:

Suche den Beginn von `_llm_chunks()`. Der erste Eintrag in `messages` ist der System-Prompt. Ersetze:
```python
messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
```
durch:
```python
messages = [{"role": "system", "content": get_base_system_prompt()}]
```

### 4d. Context um Tageszeit und Wochentag erweitern:

In `build_context()` — füge am **Anfang des zurückgegebenen `context` Strings** Folgendes hinzu:

Suche die Zeile:
```python
context = f"""KONTEXT DES USERS:
```

Ersetze durch:
```python
from datetime import datetime, timezone as tz
now = datetime.now(tz.utc)
weekday_de = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]

context = f"""KONTEXT DES USERS:
Aktuell: {weekday_de[now.weekday()]}, {now.strftime('%H:%M')} UTC

```

**Wichtig:** Den Rest des Strings (`Recovery Score: ...` etc.) unverändert lassen.

---

## 5. Fix: `langchain_agent.py` — Unified Prompt

### Datei: `backend/app/services/langchain_agent.py`

**Lese die Datei. Führe diese Änderungen durch:**

### 5a. Imports ergänzen:
```python
from app.services.coach_prompts import get_base_system_prompt, get_autonomous_system_prompt
```

### 5b. Den hartcodierten `SYSTEM_PROMPT` String löschen:
Lösche den kompletten `SYSTEM_PROMPT = """..."""` Block am Anfang der Datei.

### 5c. In `_build_executor()` — Prompt dynamisch laden:

Suche den Prompt-Aufbau in `_build_executor()`. Ersetze:
```python
prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ...
])
```
durch:
```python
prompt = ChatPromptTemplate.from_messages([
    ("system", get_base_system_prompt()),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])
```

### 5d. In `run_autonomous()` — Autonomous Prompt nutzen:

In der Methode `run_autonomous()`, beim Erstellen des Prompts (dort wo `SYSTEM_PROMPT + "\n\nDu arbeitest autonom..."` steht), ersetze durch:
```python
prompt = ChatPromptTemplate.from_messages([
    ("system", get_autonomous_system_prompt()),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])
```

---

## 6. Fix: Autonomous Monitor — Cooldown via Redis

### Datei: `backend/app/services/autonomous_monitor.py`

**Problem:** Ohne Cooldown sendet der Monitor bei jedem 30-Minuten-Lauf eine Nachricht — das könnten 48 Nachrichten/Tag sein.

**Lese die Datei. Führe diese Änderungen durch:**

### 6a. Imports ergänzen (oben):
```python
import redis.asyncio as aioredis
from app.core.config import settings
from app.services.coach_prompts import get_detection_prompt
```

### 6b. Cooldown-Konstante und Redis-Helper hinzufügen (nach den Imports, vor `DETECTION_PROMPT`):

```python
# Mindest-Abstand zwischen zwei autonomen Aktionen pro User
COOLDOWN_HOURS = 6
COOLDOWN_KEY_PREFIX = "autonomous_monitor_last_action:"


async def _get_redis():
    """Erstellt Redis-Verbindung."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _is_in_cooldown(user_id: str) -> bool:
    """Prüft ob User in Cooldown-Phase ist (letzte Aktion < COOLDOWN_HOURS ago)."""
    try:
        r = await _get_redis()
        key = f"{COOLDOWN_KEY_PREFIX}{user_id}"
        exists = await r.exists(key)
        await r.aclose()
        return bool(exists)
    except Exception:
        return False  # Bei Redis-Fehler: kein Cooldown (fail open)


async def _set_cooldown(user_id: str):
    """Setzt Cooldown für User (COOLDOWN_HOURS Stunden)."""
    try:
        r = await _get_redis()
        key = f"{COOLDOWN_KEY_PREFIX}{user_id}"
        await r.setex(key, COOLDOWN_HOURS * 3600, "1")
        await r.aclose()
    except Exception:
        pass
```

### 6c. Den `DETECTION_PROMPT` String löschen:
Lösche den kompletten `DETECTION_PROMPT = """..."""` Block.

### 6d. In `_classify_conversation()` — neuen Prompt nutzen:

Suche die Stelle wo `DETECTION_PROMPT.format(messages=messages_text)` aufgerufen wird.
Ersetze durch:
```python
"content": get_detection_prompt(messages_text)
```

### 6e. In `run_autonomous_monitor()` — Cooldown einbauen:

Suche den `for user in users:` Loop. Nach `if not convs: continue` füge ein:

```python
# Cooldown prüfen — nicht mehr als 1x alle 6h handeln
if await _is_in_cooldown(str(user.id)):
    continue
```

Und NACH dem erfolgreichen Speichern der Conversation-Note (`db.add(note); await db.flush()`), füge ein:
```python
# Cooldown setzen
await _set_cooldown(str(user.id))
```

---

## 7. Fix: Sleep Coach — Dynamische LLM-Tipps

### Datei: `backend/app/services/sleep_coach.py`

**Problem:** Die 7 statischen Tipps sind immer gleich und nicht personalisiert.

**Lese die Datei. Führe diese Änderungen durch:**

### 7a. `SLEEP_TIPS` Liste löschen:
Lösche den kompletten `SLEEP_TIPS = [...]` Block.

### 7b. `send_evening_sleep_tips()` überarbeiten:

Suche den Abschnitt `# Personalisierten Tipp generieren` und ersetze alles danach (bis zum `message = f"🌙 **Schlaftipp..."`) durch:

```python
# Personalisierte LLM-Empfehlung generieren
tip_prompt = f"""Du bist ein Schlafcoach für Ausdauersportler. Schreibe EINEN kurzen, konkreten Schlaftipp für heute Abend.

Nutzer-Kontext:
- Durchschnittlicher Schlaf letzte Tage: {f"{sleep_hours}h" if latest_metrics else "unbekannt"}
- Aktueller Wochentag: {__import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%A")}

Regeln:
- 2-3 Sätze maximal
- Konkret und actionable (nicht "schlaf mehr")
- Wissenschaftlich fundiert
- Auf Deutsch
- KEIN Markdown-Bold, normaler Text

Schreibe nur den Tipp, keine Einleitung."""

tip = await _call_llm(tip_prompt)
if not tip:
    tip = "Versuche heute 30 Minuten vor dem Schlafen alle Bildschirme auszuschalten und stattdessen ein Buch zu lesen. Das reduziert Cortisol und verbessert deine Einschlafzeit."

# Kontext-Nachricht
if latest_metrics:
    avg_sleep = sum(m.sleep_duration_min or 0 for m in latest_metrics) / len(latest_metrics)
    sleep_hours = round(avg_sleep / 60, 1)
    if sleep_hours < 6:
        context = f"⚠️ Dein Schlaf-Durchschnitt: nur {sleep_hours}h — Ziel sind 7-9h für optimale Regeneration."
    elif sleep_hours >= 7.5:
        context = f"✅ Dein Schlaf-Durchschnitt: {sleep_hours}h — weiter so!"
    else:
        context = f"📈 Dein Schlaf-Durchschnitt: {sleep_hours}h — noch etwas Potenzial nach oben."
else:
    context = ""
```

---

## 8. Fix: Meal Planner — Trainingsbelastung berücksichtigen

### Datei: `backend/app/services/meal_planner.py`

**Lese die Datei. Führe diese Änderungen durch:**

### 8a. Imports ergänzen:
```python
from datetime import date, timedelta
```

### 8b. `generate_weekly_plan()` Signatur erweitern:

Ändere die Signatur von:
```python
async def generate_weekly_plan(self, user_id: str, kalorien_ziel: int, protein_ziel_g: int) -> str:
```
zu:
```python
async def generate_weekly_plan(
    self,
    user_id: str,
    kalorien_ziel: int,
    protein_ziel_g: int,
    training_context: str = "",
) -> str:
```

### 8c. Prompt erweitern — Trainingsbelastung einbauen:

Im Prompt-String — ergänze nach `Tagesziel: {kalorien_ziel} kcal, {protein_ziel_g}g Protein` folgendes:

```python
training_section = f"\nTrainingsbelastung dieser Woche:\n{training_context}" if training_context else ""
```

Und füge `{training_section}` nach der Tagesziel-Zeile im Prompt ein.

### 8d. In `langchain_agent.py` — Tool `create_weekly_meal_plan` anpassen:

Im Tool `create_weekly_meal_plan` — nach dem `get_training_plan()` Aufruf, baue Trainings-Kontext auf und übergebe ihn:

Suche in `langchain_agent.py` das Tool `create_weekly_meal_plan`. Ersetze den Body:

```python
@tool
async def create_weekly_meal_plan(kalorien_ziel: int, protein_ziel_g: int) -> str:
    """Erstellt einen vollständigen 7-Tage Speiseplan mit Rezepten, angepasst an die Trainingsbelastung der Woche. kalorien_ziel: tägliches Kalorienziel. protein_ziel_g: tägliches Proteinziel in Gramm."""
    from app.services.meal_planner import MealPlanner

    # Trainingsplan der aktuellen Woche laden für Kontext
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    plan_result = await db.execute(
        select(TrainingPlan)
        .where(
            TrainingPlan.user_id == user_id,
            TrainingPlan.date >= week_start,
            TrainingPlan.date < week_start + timedelta(days=7),
        )
        .order_by(TrainingPlan.date)
    )
    plans = plan_result.scalars().all()

    training_context = ""
    if plans:
        total_min = sum(p.duration_min or 0 for p in plans)
        high_intensity = [p for p in plans if (p.intensity_zone or 0) >= 4]
        training_context = (
            f"- Gesamtvolumen: {total_min} Minuten diese Woche\n"
            f"- Harte Einheiten (Zone 4-5): {len(high_intensity)}\n"
            f"- Details: " + ", ".join([f"{p.date.strftime('%a')} {p.workout_type}({p.duration_min}min Z{p.intensity_zone})" for p in plans])
        )

    planner = MealPlanner()
    return await planner.generate_weekly_plan(user_id, kalorien_ziel, protein_ziel_g, training_context)
```

---

## 9. Fix: Frontend — Besseres Markdown Rendering

### Datei: `frontend/src/components/chat/MessageBubble.tsx`

**Lese die Datei zuerst.**

**Problem:** Aktuell wird `**text**` nur durch einen simplen String-Replace in `<span class="font-pixel text-blue">` umgewandelt. Das ist fehleranfällig und nicht vollständig.

**Ersetze die komplette Datei durch diese verbesserte Version:**

```tsx
import React from "react";

interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

function formatContent(text: string): React.ReactNode[] {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];

  lines.forEach((line, lineIdx) => {
    // Leerzeile → Absatz-Abstand
    if (line.trim() === "") {
      nodes.push(<br key={`br-${lineIdx}`} />);
      return;
    }

    // Überschrift ## / ###
    if (line.startsWith("### ")) {
      nodes.push(
        <div key={lineIdx} className="font-bold text-blue-400 mt-2 mb-1 uppercase text-xs tracking-wider">
          {line.replace("### ", "")}
        </div>
      );
      return;
    }
    if (line.startsWith("## ")) {
      nodes.push(
        <div key={lineIdx} className="font-bold text-blue-300 mt-3 mb-1 text-sm uppercase tracking-wider border-b border-blue-500 pb-1">
          {line.replace("## ", "")}
        </div>
      );
      return;
    }

    // Aufzählungspunkte - / •
    if (line.startsWith("- ") || line.startsWith("• ")) {
      const content = line.replace(/^[-•]\s/, "");
      nodes.push(
        <div key={lineIdx} className="flex gap-2 ml-2">
          <span className="text-blue-400 flex-shrink-0">›</span>
          <span>{renderInline(content)}</span>
        </div>
      );
      return;
    }

    // Nummerierte Liste
    const numberedMatch = line.match(/^(\d+)\.\s(.+)/);
    if (numberedMatch) {
      nodes.push(
        <div key={lineIdx} className="flex gap-2 ml-2">
          <span className="text-blue-400 flex-shrink-0 font-bold">{numberedMatch[1]}.</span>
          <span>{renderInline(numberedMatch[2])}</span>
        </div>
      );
      return;
    }

    // Trennlinie ---
    if (line.trim() === "---") {
      nodes.push(<hr key={lineIdx} className="border-blue-800 my-2" />);
      return;
    }

    // Normale Zeile mit Inline-Formatierung
    nodes.push(
      <div key={lineIdx} className="leading-relaxed">
        {renderInline(line)}
      </div>
    );
  });

  return nodes;
}

function renderInline(text: string): React.ReactNode {
  // Bold **text** und *text* (italic wird auch bold)
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i} className="text-blue-300 font-bold">{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("*") && part.endsWith("*")) {
          return <em key={i} className="text-gray-300 italic">{part.slice(1, -1)}</em>;
        }
        // Emojis und normaler Text
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

export default function MessageBubble({ role, content, created_at }: MessageBubbleProps) {
  const isCoach = role === "assistant";
  const time = created_at
    ? new Date(created_at).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })
    : "";

  return (
    <div className={`flex ${isCoach ? "justify-start" : "justify-end"} mb-3`}>
      {isCoach && (
        <div className="w-7 h-7 flex-shrink-0 border border-blue-500 flex items-center justify-center text-xs text-blue-400 mr-2 mt-1">
          C
        </div>
      )}
      <div
        className={`max-w-[85%] p-3 border text-sm ${
          isCoach
            ? "border-blue-700 bg-black text-gray-100"
            : "border-gray-600 bg-gray-900 text-gray-200 ml-2"
        }`}
        style={{ fontFamily: "monospace" }}
      >
        <div className="space-y-0.5">{formatContent(content)}</div>
        {time && (
          <div className="text-xs text-gray-600 mt-2 text-right">{time}</div>
        )}
      </div>
    </div>
  );
}
```

---

## 10. Fix: useCoach.ts — SSE Parser für Newlines

### Datei: `frontend/src/hooks/useCoach.ts`

**Lese die Datei zuerst.**

**Problem:** Wenn der Backend-Stream `\ndata: ` als Newline-Escaping nutzt, muss der Frontend-Parser das rückgängig machen.

**Suche die Stelle im `sendMessage()` oder im Reader-Loop wo SSE-Zeilen geparsed werden.** Es gibt einen Block der ungefähr so aussieht:

```typescript
const text = decoder.decode(value);
const lines = text.split("\n");
for (const line of lines) {
  if (line.startsWith("data: ")) {
    const data = line.slice(6);
    // ...
  }
}
```

**Ersetze die SSE-Parsing-Logik durch diese robustere Version:**

```typescript
// Akkumulierter Buffer für unvollständige Chunks
let buffer = "";

// Im Reader-Loop:
const text = decoder.decode(value, { stream: true });
buffer += text;

// SSE Events aus Buffer extrahieren (getrennt durch \n\n)
const events = buffer.split("\n\n");
buffer = events.pop() ?? ""; // Letztes (unvollständiges) Event zurückbehalten

for (const event of events) {
  // Mehrzeilige SSE-Chunks zusammenführen: "data: line1\ndata: line2" → "line1\nline2"
  const dataLines = event
    .split("\n")
    .filter((l) => l.startsWith("data: "))
    .map((l) => l.slice(6));

  const data = dataLines.join("\n");

  if (!data || data === "[DONE]") continue;

  // Streaming-Message aktualisieren
  setMessages((prev) => {
    const last = prev[prev.length - 1];
    if (last?.role === "assistant" && last.id === assistantMsgId) {
      return [...prev.slice(0, -1), { ...last, content: last.content + data }];
    }
    return prev;
  });
}
```

**WICHTIG:** Du musst die Variable `assistantMsgId` aus dem Kontext übernehmen — der genaue Variablenname hängt vom bestehenden Code ab. Lese die Datei, passe die Integration entsprechend an, ohne den Rest der Logik zu brechen.

---

## 11. Implementierungsreihenfolge

Implementiere EXAKT in dieser Reihenfolge:

1. **`coach_prompts.py` erstellen** (§3) — Abhängigkeit für alle anderen
2. **`coach_agent.py` fixen** (§1 + §4) — Thinking-Tokens + Prompt + Context
3. **`langchain_agent.py` fixen** (§2 + §5) — Stream-Filter + Prompt + _tool_status_message
4. **`autonomous_monitor.py` fixen** (§6) — Cooldown + neuer Prompt
5. **`sleep_coach.py` fixen** (§7) — Dynamische Tipps
6. **`meal_planner.py` fixen** (§8) — Training-Kontext
7. **`MessageBubble.tsx` ersetzen** (§9) — Frontend Markdown
8. **`useCoach.ts` fixen** (§10) — SSE Parser

---

## 12. Wichtige Hinweise

### Backend nach Änderungen
```bash
docker-compose restart backend
docker-compose logs backend --tail=30  # Auf ImportError prüfen
```

### Frontend nach Änderungen
```bash
# Frontend hat Hot-Reload via Next.js — kein Neustart nötig
# ABER: wenn Container-Probleme:
docker-compose restart frontend
```

### Redis-Verfügbarkeit
- Redis läuft bereits im Docker-Stack (`redis_url` in Settings)
- `redis.asyncio` ist bereits in `requirements.txt` als `redis==5.0.4`
- Kein zusätzliches Package nötig

### Zirkuläre Imports vermeiden
- `coach_prompts.py` darf KEINE App-Imports haben (nur stdlib `datetime`)
- Alle anderen Services importieren aus `coach_prompts`

### Test nach Implementierung
```bash
# 1. Thinking-Tokens weg?
# Chat: "Wie geht es dir?" → Antwort darf KEIN "(Denken: ...)" enthalten

# 2. Scope-Test
# Chat: "Wie programmiere ich in Python?"
# → Muss antworten: "Als TrainIQ Coach helfe ich dir nur bei Training..."

# 3. Tool-Status sichtbar
# Chat: "Zeig mir meine Metriken"
# → "📊 Lade deine Gesundheitsmetriken..." erscheint kurz

# 4. Markdown-Test
# Irgendeine Antwort mit **bold** und ## Überschriften
# → Muss korrekt gerendert werden (nicht rohe Sternchen)

# 5. Meal Plan mit Training-Kontext
curl -X POST http://localhost/api/coach/meal-plan \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"kalorien_ziel": 2400, "protein_ziel_g": 160}'
# → Antwort muss Referenz auf Trainingsbelastung der Woche enthalten
```

---

## 13. Dateistruktur nach Fixes

```
backend/app/services/
├── coach_prompts.py        ← NEU: Unified Prompts, Single Source of Truth
├── coach_agent.py          ← GEÄNDERT: Thinking fix, dynamischer Prompt+Context
├── langchain_agent.py      ← GEÄNDERT: Tool-Stream fix, _tool_status_message, unified prompt
├── autonomous_monitor.py   ← GEÄNDERT: Redis Cooldown, neuer Detection Prompt
├── sleep_coach.py          ← GEÄNDERT: Dynamische LLM-Tipps statt statischer Liste
└── meal_planner.py         ← GEÄNDERT: Training-Kontext Parameter

frontend/src/
├── components/chat/
│   └── MessageBubble.tsx   ← ERSETZT: Vollständiges Markdown Rendering
└── hooks/
    └── useCoach.ts         ← GEÄNDERT: Robuster SSE Buffer-Parser
```
