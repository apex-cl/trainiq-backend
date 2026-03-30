# AGENT B — Frontend: Fehlende Features, UX-Lücken & Bugfixes

> **Arbeitsverzeichnis:** `/Users/abu/Projekt/trainiq/frontend/src/`
> **Lies jede Datei vollständig vor dem Bearbeiten.**
> **Keine neuen npm-Pakete. Kein Styling erfinden — bestehende Klassen verwenden.**

---

## KRITISCHE BUGFIXES

### Bug B-FIX-1 — `useCoach.ts`: SSE Stream-Loop bricht nicht korrekt ab

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/hooks/useCoach.ts`

Das aktuelle `break` in der `for...of`-Schleife bricht nur aus der inneren Schleife aus, NICHT aus dem `while(true)` Loop. Das bedeutet der SSE-Stream liest weiter, auch nachdem `[DONE]` empfangen wurde. Außerdem werden `\r` Zeichen im Payload nicht entfernt.

**Ändere beide `sendMessage` und `sendImage` SSE-Parsing-Blöcke** (finde sie via Suche nach `if (payload === "[DONE]")`):

In **beiden** Loops — ersetze den gesamten `while(true)` Block:

```typescript
if (reader) {
  let done = false;
  while (!done) {
    const { done: streamDone, value } = await reader.read();
    if (streamDone) break;
    const chunk = decoder.decode(value, { stream: true });
    for (const line of chunk.split("\n")) {
      if (line.startsWith("data: ")) {
        const payload = line.slice(6).trim(); // trim() entfernt \r
        if (payload === "[DONE]") { done = true; break; }
        if (payload) {
          full += payload;
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: full } : m))
          );
        }
      }
    }
  }
}
```

---

### Bug B-FIX-2 — `metriken/page.tsx`: `useQueryClient` fehlt in Wellbeing-Submit

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/(app)/metriken/page.tsx`

Prüfe ob `qc.invalidateQueries({ queryKey: ["metrics-today"] })` in `submitWellbeing` aufgerufen wird. Falls nein, füge es hinzu. Falls ja — kein Fix nötig.

---

## FEHLENDE FEATURES IMPLEMENTIEREN

### Feature B-1 — `not-found.tsx` und `loading.tsx` prüfen

**Dateien:**
- `/Users/abu/Projekt/trainiq/frontend/src/app/not-found.tsx`
- `/Users/abu/Projekt/trainiq/frontend/src/app/loading.tsx`

Prüfe ob die Dateien existieren. Falls eine fehlt, erstelle sie:

**`not-found.tsx`** (falls fehlend):
```tsx
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center px-6">
      <div className="text-center max-w-sm">
        <p className="font-pixel text-blue" style={{ fontSize: 88, lineHeight: 1 }}>404</p>
        <p className="text-xs tracking-widest uppercase text-textDim font-sans mt-4 mb-6">
          Seite nicht gefunden
        </p>
        <Link
          href="/dashboard"
          className="inline-block border border-blue text-blue text-xs tracking-widest uppercase font-sans px-8 py-3 hover:bg-blueDim transition-colors"
        >
          › Zum Dashboard
        </Link>
      </div>
    </div>
  );
}
```

**`loading.tsx`** (falls fehlend):
```tsx
export default function Loading() {
  return (
    <div className="min-h-screen bg-bg flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <span className="font-pixel text-blue text-3xl animate-pulse">TRAINIQ</span>
        <div className="flex gap-1">
          <span className="w-1.5 h-1.5 bg-blue animate-bounce" style={{ animationDelay: "0ms" }} />
          <span className="w-1.5 h-1.5 bg-blue animate-bounce" style={{ animationDelay: "150ms" }} />
          <span className="w-1.5 h-1.5 bg-blue animate-bounce" style={{ animationDelay: "300ms" }} />
        </div>
      </div>
    </div>
  );
}
```

---

### Feature B-2 — Training Page: "Heute" Button in 7-Tage Strip

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/(app)/training/page.tsx`

Es gibt keinen "Zurück zu Heute" Button wenn der User auf einen anderen Tag klickt. Füge ihn hinzu.

Im Header-Block (nach `<span className="font-pixel text-blue text-xl">TRAINING</span>`) füge hinzu, falls `selected !== today`:

```tsx
{selected !== today && (
  <button
    onClick={() => setSelected(today)}
    className="text-xs font-sans text-blue tracking-widest uppercase hover:underline"
  >
    ← Heute
  </button>
)}
```

Der Header-Block soll danach so aussehen:
```tsx
<div className="px-5 pt-5 pb-4 border-b border-border flex justify-between items-center">
  <span className="font-pixel text-blue text-xl">TRAINING</span>
  {selected !== today && (
    <button
      onClick={() => setSelected(today)}
      className="text-xs font-sans text-blue tracking-widest uppercase hover:underline"
    >
      ← Heute
    </button>
  )}
</div>
```

---

### Feature B-3 — Einstellungen: Passwort ändern (UI-Only mit Info-Text)

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/(app)/einstellungen/page.tsx`

Es gibt keinen Passwortänderungs-Flow. Füge einen informativen Block hinzu (kein Backend-Endpoint nötig — User wird zur Erklärung geleitet).

Finde den "Abmelden" Block (ca. Zeile 306-315). Füge **davor** einen neuen Block ein:

```tsx
{/* Passwort */}
<div className="px-5 py-4 border-b border-border">
  <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-3">Sicherheit</p>
  <div className="flex justify-between items-center">
    <div>
      <p className="text-xs font-sans text-textMain">Passwort</p>
      <p className="text-xs font-sans text-textDim mt-0.5">••••••••</p>
    </div>
    <span className="text-xs font-sans text-textDim tracking-widest uppercase">Über Support ändern</span>
  </div>
</div>
```

---

### Feature B-4 — Dashboard: Klickbarer Recovery Score → `/metriken`

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/(app)/dashboard/page.tsx`

Der Recovery Block (Zeilen 106-125) ist nicht verlinkt. User sollen beim Klick auf den Score zu `/metriken` gelangen.

Wrapping des gesamten Recovery-Block `<div className="px-5 pt-4 pb-5 border-b border-border">` mit einem `<Link>`:

Ersetze:
```tsx
<div className="px-5 pt-4 pb-5 border-b border-border">
```

Mit:
```tsx
<Link href="/metriken" className="block px-5 pt-4 pb-5 border-b border-border hover:bg-surface transition-colors">
```

Und schließe entsprechend mit `</Link>` (statt `</div>`).

---

### Feature B-5 — Globaler Error-Handler für unbehandelte Promise-Rejections

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/providers.tsx`

Füge einen globalen `unhandledrejection`-Handler hinzu der stille API-Fehler loggiert:

Nach dem `useEffect` für `init()`:
```tsx
useEffect(() => {
  const handler = (event: PromiseRejectionEvent) => {
    // Stille 401/404 nicht als Fehler loggen
    const status = event.reason?.response?.status;
    if (status && [401, 404].includes(status)) return;
    console.error("[TrainIQ] Unhandled rejection:", event.reason);
  };
  window.addEventListener("unhandledrejection", handler);
  return () => window.removeEventListener("unhandledrejection", handler);
}, []);
```

---

### Feature B-6 — Ernaehrung Page: Leere Mahlzeiten-Liste Verbesserung

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/(app)/ernaehrung/page.tsx`

Die leere Mahlzeiten-Liste zeigt nur "Noch keine Mahlzeiten heute." Füge einen Call-To-Action hinzu:

Ersetze:
```tsx
{mealList.length === 0 ? (
  <p className="text-sm font-sans text-textDim">Noch keine Mahlzeiten heute.</p>
```

Mit:
```tsx
{mealList.length === 0 ? (
  <div className="border border-dashed border-border p-6 text-center">
    <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">Keine Mahlzeiten</p>
    <p className="text-sm font-sans text-textDim">Fotografiere dein Essen mit dem Kamera-Button oben.</p>
  </div>
```

---

### Feature B-7 — Chat Page: Fehlermeldung wenn Nachricht zu lang

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/(app)/chat/page.tsx`

Füge eine Warnung hinzu wenn die Eingabe zu lang ist (>1000 Zeichen):

Im Input-Bereich — nach `<span className="cursor-blink text-blue font-mono text-sm">_</span>` und vor dem schließenden `</div>` des Input-Containers:

```tsx
{input.length > 900 && (
  <span className="text-[10px] font-sans text-danger shrink-0">
    {1000 - input.length}
  </span>
)}
```

Außerdem im `handleSend`:
```tsx
const handleSend = () => {
  if (!input.trim() || loading || input.length > 1000) return;
```

---

### Feature B-8 — Metriken Page: Puls-Sektion (fehlende Visualisierung)

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/(app)/metriken/page.tsx`

Füge nach dem "Stress Chart" Block (nach dem Stress-`</div>`) einen Ruhepuls Chart ein:

```tsx
{/* Ruhepuls Chart */}
<div className="px-5 py-5 border-b border-border">
  <div className="flex justify-between items-center mb-4">
    <p className="text-xs tracking-widests uppercase text-textDim font-sans">Ruhepuls — 7 Tage</p>
    <p className="font-pixel text-textMain" style={{ fontSize: 16 }}>{today?.resting_hr ?? "—"}bpm</p>
  </div>
  {hasValues ? (
    <div className="border border-border p-3">
      <ResponsiveContainer width="100%" height={80}>
        <LineChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <XAxis dataKey="day" tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <Tooltip content={<CustomTooltip />} />
          <Line type="monotone" dataKey="hr" stroke="#2563EB" strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: "#2563EB" }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  ) : <EmptyChart />}
</div>
```

Stelle sicher dass `chartData` das Feld `hr` hat — prüfe die chartData-Berechnung (ca. Zeile 39-45). Es sollte `hr: d.resting_hr ?? 0` beinhalten. Falls nicht, füge es hinzu.

---

### Feature B-9 — Training Page: "Plan generieren" Button wenn kein Plan vorhanden

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/(app)/training/page.tsx`

Der Leerzustand zeigt nur einen Link zu `/onboarding`. Wenn der User schon Ziele hat (aber kein Plan generiert wurde), füge einen "Plan jetzt erstellen" Button hinzu:

Ersetze den leeren `week.length === 0` Block:

```tsx
) : week.length === 0 ? (
  <div className="px-5 py-12">
    <div className="border border-dashed border-border p-8 text-center">
      <p className="font-pixel text-xs text-textDim uppercase tracking-widest mb-4">
        Kein Trainingsplan
      </p>
      <p className="text-sm font-sans text-textDim mb-6">
        Trage deine Ziele ein damit der Coach einen Plan erstellt.
      </p>
      <div className="flex flex-col gap-3">
        <a href="/onboarding" className="inline-block border border-blue text-blue px-6 py-2 text-xs uppercase tracking-widest font-sans">
          Ziele setzen →
        </a>
        <a href="/chat" className="inline-block border border-border text-textDim px-6 py-2 text-xs uppercase tracking-widest font-sans hover:border-blue hover:text-blue transition-colors">
          › Coach nach Plan fragen
        </a>
      </div>
    </div>
  </div>
```

---

### Feature B-10 — Dashboard: Loading-Skeleton für Ernährungs-Sektion

**Datei:** `/Users/abu/Projekt/trainiq/frontend/src/app/(app)/dashboard/page.tsx`

Der Ernährungs-Block (Zeile ~182) zeigt sofort die Balken mit 0-Werten während er lädt. Füge eine Skeleton-Ansicht hinzu:

Wrapping des kompletten Makro-Balken-Bereichs:

Füge nach `<p className="text-xs tracking-widests uppercase text-textDim font-sans">Ernährung</p>` ein:

```tsx
{nutritionLoading ? (
  <div className="space-y-3 mt-2">
    {[1,2,3,4].map(i => (
      <div key={i} className="flex items-center gap-3">
        <div className="w-16 h-3 bg-border animate-pulse" />
        <div className="flex-1 h-[3px] bg-border animate-pulse" />
        <div className="w-12 h-3 bg-border animate-pulse" />
      </div>
    ))}
  </div>
) : (
  <>
    {/* ... (bestehende Makro-Balken) ... */}
  </>
)}
```

**WICHTIG:** `nutritionLoading` ist bereits als Variable definiert (aus dem `useQuery` Call). Nutze sie.

---

## ABSCHLUSSKONTROLLE FÜR AGENT B

1. `useCoach.ts` SSE-Loop bricht korrekt bei `[DONE]` ab, ohne weiter zu lesen
2. Training-Page hat "← Heute" Button der zum heutigen Tag springt
3. Einstellungen hat Sicherheits-Block (UI-Only)
4. Dashboard Recovery Score ist mit `/metriken` verlinkt
5. Leere Mahlzeiten-Liste hat Call-To-Action Text
6. Chat begrenzt Eingabe auf 1000 Zeichen mit Countdown
7. Metriken-Page hat Ruhepuls-Chart als 4. Chart
8. Training-Page leerer Zustand hat zweiten Button "Coach nach Plan fragen"
9. Dashboard Ernährungs-Sektion zeigt Skeleton während Daten laden
10. `not-found.tsx` und `loading.tsx` existieren

**Keine neuen npm-Pakete installieren!**
