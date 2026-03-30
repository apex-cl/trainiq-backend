"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { SportIcon } from "@/components/ui/SportIcon";

const SPORTS = [
  { id: "running",   label: "LAUFEN" },
  { id: "cycling",   label: "RADFAHREN" },
  { id: "swimming",  label: "SCHWIMMEN" },
  { id: "triathlon", label: "TRIATHLON" },
];

const FITNESS_LEVELS = [
  { id: "beginner",     label: "EINSTEIGER" },
  { id: "intermediate", label: "FORTGESCHRITTEN" },
  { id: "advanced",     label: "PROFI" },
];

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [selectedSports, setSelectedSports] = useState<string[]>([]);
  const [goal, setGoal] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [weeklyHours, setWeeklyHours] = useState(5);
  const [fitnessLevel, setFitnessLevel] = useState("intermediate");
  const [loading, setLoading] = useState(false);

  // Optional: Personal data
  const [birthDate, setBirthDate] = useState("");
  const [weightKg, setWeightKg] = useState("");
  const [heightCm, setHeightCm] = useState("");

  // Strava State
  const [stravaAvailable, setStravaAvailable] = useState(false);
  const [stravaConnected, setStravaConnected] = useState(false);

  useEffect(() => {
    // Check if Strava is available in backend config
    const checkStatus = async () => {
      try {
        const resp = await api.get("/watch/status");
        setStravaAvailable(resp.data.strava_available);
        const isConnected = resp.data.connected.some((c: any) => c.provider === "strava");
        setStravaConnected(isConnected);
      } catch (err) {
        console.error("Watch status error", err);
      }
    };
    checkStatus();

    // Check if coming back from OAuth redirect
    if (typeof window !== "undefined" && window.location.search.includes("strava=connected")) {
      setStravaConnected(true);
    }
  }, []);

  const handleStravaConnect = async () => {
    setLoading(true);
    try {
      const resp = await api.get("/watch/strava/connect");
      if (resp.data.auth_url) {
        window.location.href = resp.data.auth_url;
      }
    } catch (err) {
      console.error("Strava connect error", err);
    } finally {
      setLoading(false);
    }
  };

  const toggleSport = (id: string) =>
    setSelectedSports((prev) => prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]);

  const saveGoals = async () => {
    setLoading(true);
    try {
      await api.post("/user/goals", {
        sport: selectedSports[0] ?? "running",
        goal_description: goal,
        target_date: targetDate || null,
        weekly_hours: weeklyHours,
        fitness_level: fitnessLevel,
      });
      setStep(3);
    } catch (err) {
      console.error("Goals API error", err);
      setStep(3); // Continue anyway in dev mode or show error
    } finally {
      setLoading(false);
    }
  };

  const finish = async () => {
    setLoading(true);
    try {
      await api.post("/watch/sync");
    } catch { /* ignore */ }
    router.replace("/dashboard");
  };

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-between px-6 py-10 max-w-sm mx-auto">

      {/* Progress dots */}
      <div className="flex gap-2 self-center">
        {[1, 2, 3].map((s) => (
          <div key={s} className={`h-[3px] w-8 transition-colors ${s <= step ? "bg-blue" : "bg-border"}`} />
        ))}
      </div>

      {/* Step 1 */}
      {step === 1 && (
        <div className="flex-1 flex flex-col justify-center w-full gap-6">
          <div>
            <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">Schritt 1 / 3</p>
            <h1 className="font-pixel text-textMain" style={{ fontSize: 36 }}>DEIN SPORT</h1>
            <p className="text-sm font-sans text-textDim mt-1">Mehrfachauswahl möglich.</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {SPORTS.map((s) => (
              <button
                key={s.id}
                onClick={() => toggleSport(s.id)}
                className={`border p-5 flex flex-col items-center gap-2 transition-colors ${
                  selectedSports.includes(s.id)
                    ? "border-blue bg-blueDim"
                    : "border-border hover:border-textDim"
                }`}
              >
                <SportIcon sport={s.id} size={24} className="text-textDim" />
                <span className="text-xs tracking-widest uppercase font-sans text-textMain">{s.label}</span>
              </button>
            ))}
          </div>
          <button
            onClick={() => selectedSports.length > 0 && setStep(2)}
            disabled={selectedSports.length === 0}
            className="w-full border border-blue text-blue text-xs tracking-widest uppercase font-sans py-3.5 hover:bg-blueDim transition-colors disabled:opacity-30"
          >
            Weiter ──→
          </button>
        </div>
      )}

      {/* Step 2 */}
      {step === 2 && (
        <div className="flex-1 flex flex-col justify-center w-full gap-6">
          <div>
            <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">Schritt 2 / 3</p>
            <h1 className="font-pixel text-textMain" style={{ fontSize: 36 }}>DEIN ZIEL</h1>
          </div>
          <div className="border border-border flex items-start px-4 py-3 gap-2">
            <span className="font-mono text-blue mt-0.5">›</span>
            <textarea
              placeholder="z.B. Halbmarathon unter 2 Stunden in 6 Monaten"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={3}
              className="flex-1 bg-transparent text-sm font-sans text-textMain placeholder-textDim outline-none resize-none"
            />
          </div>
          <div className="border border-border px-4 py-3">
            <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">Zieldatum (optional)</p>
            <input
              type="date"
              value={targetDate}
              onChange={(e) => setTargetDate(e.target.value)}
              className="bg-transparent text-sm font-sans text-textMain outline-none w-full"
            />
          </div>
          <div className="border border-border px-4 py-3">
            <div className="flex justify-between mb-2">
              <p className="text-xs tracking-widest uppercase text-textDim font-sans">Wöchentliche Stunden</p>
              <p className="font-pixel text-blue" style={{ fontSize: 18 }}>{weeklyHours}h</p>
            </div>
            <input
              type="range" min={1} max={20} value={weeklyHours}
              onChange={(e) => setWeeklyHours(Number(e.target.value))}
              className="w-full accent-blue h-[3px]"
            />
            <div className="flex justify-between mt-1">
              <span className="text-xs font-sans text-textDim">1h</span>
              <span className="text-xs font-sans text-textDim">20h</span>
            </div>
          </div>

          {/* Fitnesslevel */}
          <div>
            <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">Fitnesslevel</p>
            <div className="flex gap-2">
              {FITNESS_LEVELS.map((f) => (
                <button
                  key={f.id}
                  onClick={() => setFitnessLevel(f.id)}
                  className={`flex-1 border py-2 text-xs tracking-widest uppercase font-sans transition-colors ${
                    fitnessLevel === f.id
                      ? "border-blue text-blue bg-blueDim"
                      : "border-border text-textDim hover:border-textDim"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-3">
            <button onClick={() => setStep(1)} className="flex-1 border border-border text-textDim text-xs tracking-widest uppercase font-sans py-3 hover:border-textDim transition-colors">
              ← Zurück
            </button>
            <button
              onClick={saveGoals}
              disabled={goal.length < 3 || loading}
              className="flex-1 border border-blue text-blue text-xs tracking-widest uppercase font-sans py-3 hover:bg-blueDim transition-colors disabled:opacity-30"
            >
              {loading ? "Wird gespeichert..." : "Weiter ──→"}
            </button>
          </div>
        </div>
      )}

      {/* Step 3 */}
      {step === 3 && (
        <div className="flex-1 flex flex-col justify-center w-full gap-6">
          <div>
            <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">Schritt 3 / 3</p>
            <h1 className="font-pixel text-textMain" style={{ fontSize: 36 }}>UHR VERBINDEN</h1>
            <p className="text-sm font-sans text-textDim mt-1">Optional — du kannst auch manuell Daten eingeben.</p>
          </div>
          <div className="flex flex-col gap-3">
            {/* Strava — funktioniert */}
            {stravaAvailable && (
              <button
                onClick={handleStravaConnect}
                disabled={loading || stravaConnected}
                className={`w-full border text-xs tracking-widest uppercase font-sans py-3.5 transition-colors text-left px-4 disabled:opacity-40 ${
                  stravaConnected ? "border-blue text-blue" : "border-border text-textMain hover:border-blue hover:text-blue"
                }`}
              >
                <span className="text-textDim mr-2">›</span> STRAVA
                {stravaConnected && <span className="float-right text-[10px] text-blue">✓ VERBUNDEN</span>}
              </button>
            )}

            {/* Noch nicht verfügbare Geräte */}
            {["GARMIN", "APPLE HEALTH", "POLAR"].map((name) => (
              <div
                key={name}
                className="w-full border border-border text-xs tracking-widest uppercase font-sans py-3.5 text-left px-4 opacity-40 flex justify-between items-center"
              >
                <span><span className="text-textDim mr-2">›</span> {name}</span>
                <span className="text-[10px] text-textDim tracking-widest">BALD</span>
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-3 mt-4">
             <button onClick={() => setStep(2)} className="w-full text-textDim text-xs tracking-widest uppercase font-sans py-2 hover:text-textMain transition-colors">
                 ← Zurück
             </button>
             <button onClick={finish} disabled={loading} className="w-full border border-border text-textDim text-xs tracking-widest uppercase font-sans py-3 hover:text-textMain hover:border-textMain transition-colors disabled:opacity-40">
                {loading ? "Wird eingerichtet..." : "Anbindung überspringen"}
             </button>
          </div>
        </div>
      )}

      <div /> {/* spacer */}
    </div>
  );
}
