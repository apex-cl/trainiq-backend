"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { LogOut, Unlink, Check, Trophy, Flame, Zap, Dumbbell, Heart, Sunrise, Timer, CheckCircle2, type LucideProps } from "lucide-react";
import type React from "react";

const ACHIEVEMENT_ICONS: Record<string, React.ComponentType<LucideProps>> = {
  Trophy, Flame, Zap, Dumbbell, Heart, Sunrise, Timer, CheckCircle2,
};
import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { useAchievements } from "@/hooks/useGamification";
import { PushNotificationSettings } from "@/components/PushNotificationSettings";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

const FITNESS_LEVELS = [
  { id: "beginner",     label: "EINSTEIGER" },
  { id: "intermediate", label: "FORTGESCHRITTEN" },
  { id: "advanced",     label: "PROFI" },
];

const SPORTS = [
  { id: "running",   label: "LAUFEN" },
  { id: "cycling",   label: "RADFAHREN" },
  { id: "swimming",  label: "SCHWIMMEN" },
  { id: "triathlon", label: "TRIATHLON" },
];

function AchievementsSection() {
  const { achievements, isLoading } = useAchievements();

  return (
    <div className="px-5 py-5 border-b border-border">
      <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-4">Abzeichen</p>
      {isLoading ? (
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex flex-col items-center gap-1">
              <div className="w-12 h-12 bg-[#EBEBEB] animate-pulse" />
              <div className="h-2 w-10 bg-[#EBEBEB] animate-pulse" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-3">
          {achievements.map((a) => {
            const unlocked = a.unlocked_at !== null;
            return (
              <div
                key={a.id}
                className={`flex flex-col items-center gap-1 py-2 border border-border ${unlocked ? "" : "opacity-30"}`}
              >
                {(() => { const Icon = ACHIEVEMENT_ICONS[a.icon] ?? Trophy; return <Icon size={22} strokeWidth={1.5} />; })()}
                <span className="text-[10px] font-sans text-textDim tracking-wider uppercase text-center leading-tight">
                  {a.title}
                </span>
              </div>
            );
          })}
        </div>
      )}
      {achievements.some((a) => a.unlocked_at) && (
        <p className="text-xs font-sans text-blue mt-3">
          {achievements.filter((a) => a.unlocked_at).length} / {achievements.length} freigeschaltet
        </p>
      )}
    </div>
  );
}

export default function EinstellungenPage() {
  const router = useRouter();
  const { user, logout } = useAuthStore();

  // Profil-State
  const [profileLoading, setProfileLoading] = useState(true);
  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [gender, setGender] = useState("");
  const [weightKg, setWeightKg] = useState<number | null>(null);
  const [heightCm, setHeightCm] = useState<number | null>(null);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);

  // Ziele-State
  const [sport, setSport] = useState("running");
  const [goalDescription, setGoalDescription] = useState("");
  const [weeklyHours, setWeeklyHours] = useState(5);
  const [fitnessLevel, setFitnessLevel] = useState("intermediate");
  const [targetDate, setTargetDate] = useState("");
  const [goalSaving, setGoalSaving] = useState(false);
  const [goalSaved, setGoalSaved] = useState(false);

  // Watch-State
  const [stravaConnected, setStravaConnected] = useState(false);
  const [watchLoading, setWatchLoading] = useState(true);
  const [disconnecting, setDisconnecting] = useState(false);
  const [showDeleteAccount, setShowDeleteAccount] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [goalError, setGoalError] = useState(false);
  const [disconnectError, setDisconnectError] = useState(false);
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordSaved, setPasswordSaved] = useState(false);

  // Profil + Ziele laden
  useEffect(() => {
    const load = async () => {
      try {
        const { data } = await api.get("/user/profile");
        setName(data.name || "");
        setBirthDate(data.birth_date || "");
        setGender(data.gender || "");
        setWeightKg(data.weight_kg);
        setHeightCm(data.height_cm);
        if (data.goals && data.goals.length > 0) {
          const g = data.goals[0];
          setSport(g.sport || "running");
          setGoalDescription(g.goal_description || "");
          setWeeklyHours(g.weekly_hours || 5);
          setFitnessLevel(g.fitness_level || "intermediate");
          setTargetDate(g.target_date || "");
        }
      } catch {
        // ignore — User sieht leere Felder
      } finally {
        setProfileLoading(false);
      }
    };
    load();
  }, []);

  // Watch-Status laden
  useEffect(() => {
    const loadWatch = async () => {
      try {
        const { data } = await api.get("/watch/status");
        const connected = (data.connected || []).some(
          (c: { provider: string }) => c.provider === "strava"
        );
        setStravaConnected(connected);
      } catch {
        // ignore
      } finally {
        setWatchLoading(false);
      }
    };
    loadWatch();
  }, []);

  const saveProfile = async () => {
    setProfileSaving(true);
    try {
      await api.put("/user/profile", {
        name,
        birth_date: birthDate || null,
        gender: gender || null,
        weight_kg: weightKg,
        height_cm: heightCm,
      });
      setProfileSaved(true);
      setTimeout(() => setProfileSaved(false), 2000);
    } catch {
      // silent
    } finally {
      setProfileSaving(false);
    }
  };

  const saveGoals = async () => {
    if (!goalDescription.trim()) return;
    setGoalSaving(true);
    try {
      await api.post("/user/goals", {
        sport,
        goal_description: goalDescription,
        weekly_hours: weeklyHours,
        fitness_level: fitnessLevel,
        target_date: targetDate || null,
      });
      setGoalSaved(true);
      setTimeout(() => setGoalSaved(false), 2000);
    } catch {
      // silent — kein crash
    } finally {
      setGoalSaving(false);
    }
  };

  const disconnectStrava = async () => {
    setDisconnecting(true);
    setDisconnectError(false);
    try {
      await api.post("/watch/strava/disconnect");
      setStravaConnected(false);
    } catch {
      setDisconnectError(true);
      setTimeout(() => setDisconnectError(false), 3000);
    } finally {
      setDisconnecting(false);
    }
  };

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  const handleDeleteAccount = async () => {
    setDeleting(true);
    try {
      await api.delete("/user/account");
      logout();
      router.replace("/login");
    } catch {
      setDeleting(false);
    }
  };

  const handleChangePassword = async () => {
    setPasswordError("");
    if (!currentPassword || !newPassword || !confirmPassword) {
      setPasswordError("Alle Felder sind erforderlich.");
      return;
    }
    if (newPassword.length < 8) {
      setPasswordError("Neues Passwort muss mindestens 8 Zeichen haben.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("Passwörter stimmen nicht überein.");
      return;
    }
    setPasswordSaving(true);
    try {
      await api.post("/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setPasswordSaved(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setTimeout(() => {
        setPasswordSaved(false);
        setShowPasswordForm(false);
      }, 2000);
    } catch {
      setPasswordError("Passwort konnte nicht geändert werden. Prüfe dein aktuelles Passwort.");
    } finally {
      setPasswordSaving(false);
    }
  };

  return (
    <div className="flex flex-col">

      {/* Header */}
      <div className="px-5 pt-5 pb-4 border-b border-border">
        <span className="font-pixel text-blue text-xl">EINSTELLUNGEN</span>
      </div>

      {/* Profil */}
      <div className="px-5 py-5 border-b border-border">
        <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-4">Konto</p>
        {profileLoading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-10 bg-border" />
            <div className="h-10 bg-border" />
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex justify-between items-center py-2 border-b border-border">
              <span className="text-xs font-sans text-textDim tracking-widest uppercase">E-Mail</span>
              <span className="text-sm font-sans text-textMain">{user?.email ?? "—"}</span>
            </div>
            {/* Name */}
            <div className="border border-border px-3 py-2">
              <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">Name</p>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
              />
            </div>
            {/* Geburtstag */}
            <div className="border border-border px-3 py-2">
              <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">Geburtstag (optional)</p>
              <input
                type="date"
                value={birthDate}
                onChange={(e) => setBirthDate(e.target.value)}
                className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
              />
            </div>
            {/* Geschlecht */}
            <div className="border border-border px-3 py-2">
              <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">Geschlecht (optional)</p>
              <select
                value={gender}
                onChange={(e) => setGender(e.target.value)}
                className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
              >
                <option value="">— Keine Angabe —</option>
                <option value="male">Männlich</option>
                <option value="female">Weiblich</option>
                <option value="other">Divers</option>
              </select>
            </div>
            {/* Körperdaten */}
            <div className="grid grid-cols-2 gap-3">
              <div className="border border-border px-3 py-2">
                <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">Gewicht (kg)</p>
                <input
                  type="number"
                  inputMode="decimal"
                  placeholder="z.B. 75"
                  value={weightKg ?? ""}
                  onChange={(e) => setWeightKg(e.target.value ? Number(e.target.value) : null)}
                  className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
                />
              </div>
              <div className="border border-border px-3 py-2">
                <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">Größe (cm)</p>
                <input
                  type="number"
                  inputMode="numeric"
                  placeholder="z.B. 180"
                  value={heightCm ?? ""}
                  onChange={(e) => setHeightCm(e.target.value ? Number(e.target.value) : null)}
                  className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
                />
              </div>
            </div>
            <button
              onClick={saveProfile}
              disabled={profileSaving}
              className="w-full border border-blue text-blue text-xs tracking-widest uppercase font-sans py-3 hover:bg-blueDim transition-colors disabled:opacity-40"
            >
              {profileSaved ? "✓ Gespeichert" : profileSaving ? "..." : "› Profil speichern"}
            </button>
          </div>
        )}
      </div>

      {/* Ziele bearbeiten */}
      <div className="px-5 py-5 border-b border-border">
        <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-5">Trainingsziel</p>

        {profileLoading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-10 bg-border" />
            <div className="h-20 bg-border" />
            <div className="h-10 bg-border" />
          </div>
        ) : (
          <div className="flex flex-col gap-4">

            {/* Sport */}
            <div>
              <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">Sport</p>
              <div className="grid grid-cols-2 gap-2">
                {SPORTS.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setSport(s.id)}
                    className={`border py-2 text-xs tracking-widest uppercase font-sans transition-colors ${
                      sport === s.id
                        ? "border-blue text-blue bg-blueDim"
                        : "border-border text-textDim hover:border-textDim"
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Ziel */}
            <div className="border border-border flex items-start px-3 py-3 gap-2">
              <span className="font-mono text-blue mt-0.5 shrink-0">›</span>
              <textarea
                placeholder="Dein Ziel, z.B. Halbmarathon unter 2 Stunden"
                value={goalDescription}
                onChange={(e) => setGoalDescription(e.target.value)}
                rows={2}
                className="flex-1 bg-transparent text-sm font-sans text-textMain placeholder-textDim outline-none resize-none"
              />
            </div>

            {/* Wochenstunden */}
            <div className="border border-border px-4 py-3">
              <div className="flex justify-between mb-2">
                <p className="text-xs tracking-widest uppercase text-textDim font-sans">Wochenstunden</p>
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

            {/* Zieldatum */}
            <div className="border border-border px-4 py-3">
              <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">Zieldatum (optional)</p>
              <input
                type="date"
                value={targetDate}
                onChange={(e) => setTargetDate(e.target.value)}
                className="bg-transparent text-sm font-sans text-textMain outline-none w-full"
              />
            </div>

            {/* Speichern Button */}
            {goalError && (
              <p className="text-xs font-sans text-danger tracking-wider">! Speichern fehlgeschlagen. Bitte versuche es erneut.</p>
            )}
            <button
              onClick={saveGoals}
              disabled={goalSaving || !goalDescription.trim()}
              className="w-full border border-blue text-blue text-xs tracking-widest uppercase font-sans py-3.5 hover:bg-blueDim transition-colors disabled:opacity-40"
            >
              {goalSaved ? (
                <span className="flex items-center justify-center gap-2">
                  <Check size={14} /> Gespeichert
                </span>
              ) : goalSaving ? "Wird gespeichert..." : "› Ziel speichern"}
            </button>
          </div>
        )}
      </div>

      {/* Verbundene Geräte */}
      <div className="px-5 py-5 border-b border-border">
        <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-4">Verbundene Geräte</p>
        {watchLoading ? (
          <div className="h-12 bg-border animate-pulse" />
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between border border-border px-4 py-3">
              <div>
                <p className="text-xs tracking-widest uppercase font-sans text-textMain">Strava</p>
                <p className={`text-xs font-sans mt-0.5 ${stravaConnected ? "text-blue" : "text-textDim"}`}>
                  {stravaConnected ? "● Verbunden" : "○ Nicht verbunden"}
                </p>
              </div>
              {stravaConnected ? (
                <button
                  onClick={disconnectStrava}
                  disabled={disconnecting}
                  className="flex items-center gap-1.5 border border-border text-textDim text-xs uppercase tracking-widest font-sans px-3 py-1.5 hover:border-danger hover:text-danger transition-colors disabled:opacity-40"
                >
                  <Unlink size={12} />
                  {disconnecting ? "..." : "Trennen"}
                </button>
              ) : (
                <button
                  onClick={() => { window.location.href = "/api/watch/strava/connect"; }}
                  className="text-xs font-sans text-blue border border-blue px-3 py-1.5 tracking-widest uppercase hover:bg-blueDim transition-colors"
                >
                  Verbinden
                </button>
              )}
            </div>

            {disconnectError && (
              <p className="text-xs font-sans text-danger tracking-wider mt-2">! Trennen fehlgeschlagen. Bitte versuche es erneut.</p>
            )}

            {/* Placeholder für weitere Geräte */}
            {["Garmin", "Apple Health", "Polar"].map((name) => (
              <div key={name} className="flex items-center justify-between border border-border px-4 py-3 opacity-40">
                <div>
                  <p className="text-xs tracking-widest uppercase font-sans text-textMain">{name}</p>
                  <p className="text-xs font-sans text-textDim mt-0.5">○ Nicht verfügbar</p>
                </div>
                <span className="text-xs font-sans text-textDim tracking-widest uppercase">Bald</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Achievements */}
      <AchievementsSection />

      {/* Push Notifications */}
      <PushNotificationSettings />

      {/* Language */}
      <LanguageSwitcher />

      {/* Passwort */}
      <div className="px-5 py-4 border-b border-border">
        <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-3">Sicherheit</p>
        {!showPasswordForm ? (
          <div className="flex justify-between items-center">
            <div>
              <p className="text-xs font-sans text-textMain">Passwort</p>
              <p className="text-xs font-sans text-textDim mt-0.5">••••••••</p>
            </div>
            <button
              onClick={() => setShowPasswordForm(true)}
              className="text-xs font-sans text-blue tracking-widest uppercase hover:underline"
            >
              Ändern
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {passwordSaved ? (
              <p className="text-xs font-sans text-blue tracking-widest uppercase">✓ Passwort geändert</p>
            ) : (
              <>
                <div className="border border-border px-3 py-2">
                  <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">Aktuelles Passwort</p>
                  <input
                    type="password"
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
                  />
                </div>
                <div className="border border-border px-3 py-2">
                  <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">Neues Passwort</p>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
                  />
                </div>
                <div className="border border-border px-3 py-2">
                  <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">Bestätigung</p>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
                  />
                </div>
                {passwordError && (
                  <p className="text-xs font-sans text-danger tracking-wider">! {passwordError}</p>
                )}
                <div className="flex gap-3">
                  <button
                    onClick={() => { setShowPasswordForm(false); setPasswordError(""); }}
                    className="flex-1 border border-border text-textDim text-xs tracking-widest uppercase font-sans py-2.5"
                  >
                    Abbrechen
                  </button>
                  <button
                    onClick={handleChangePassword}
                    disabled={passwordSaving}
                    className="flex-1 border border-blue text-blue text-xs tracking-widest uppercase font-sans py-2.5 hover:bg-blueDim transition-colors disabled:opacity-40"
                  >
                    {passwordSaving ? "..." : "› Speichern"}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Abmelden */}
      <div className="px-5 py-5">
        <button
          onClick={handleLogout}
          className="w-full flex items-center justify-center gap-2 border border-border text-textDim text-xs tracking-widest uppercase font-sans py-3.5 hover:border-danger hover:text-danger transition-colors"
        >
          <LogOut size={14} strokeWidth={1.5} />
          Abmelden
        </button>
      </div>

      {/* Account löschen */}
      <div className="px-5 pb-5">
        {!showDeleteAccount ? (
          <button
            onClick={() => setShowDeleteAccount(true)}
            className="w-full text-textDim text-xs tracking-widest uppercase font-sans py-2 hover:text-danger transition-colors"
          >
            Account löschen
          </button>
        ) : (
          <div className="border border-danger p-4">
            <p className="text-xs font-sans text-danger tracking-widest uppercase mb-3">
              ! Diese Aktion kann nicht rückgängig gemacht werden
            </p>
            <p className="text-xs font-sans text-textDim mb-4">
              Alle Daten (Training, Ernährung, Metriken, Chat) werden unwiderruflich gelöscht.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setShowDeleteAccount(false)}
                className="flex-1 border border-border text-textDim text-xs tracking-widest uppercase font-sans py-2.5"
              >
                Abbrechen
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleting}
                className="flex-1 border border-danger text-danger text-xs tracking-widest uppercase font-sans py-2.5 hover:bg-red-50 transition-colors disabled:opacity-40"
              >
                {deleting ? "..." : "Endgültig löschen"}
              </button>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
