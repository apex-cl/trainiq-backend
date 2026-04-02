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
import { useBilling } from "@/hooks/useBilling";
import { PushNotificationSettings } from "@/components/PushNotificationSettings";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { useI18n } from "@/hooks/useI18n";

// Verbindungs-Typ:
//   "oauth"       → normaler OAuth-Redirect (Strava)
//   "credentials" → E-Mail + Passwort (Garmin)
//   "file_upload" → GPX/TCX-Datei hochladen (Polar, Apple Health)
const PROVIDERS = [
  { id: "strava",  name: "Strava",       type: "oauth" as const,       connectPath: "/watch/strava/connect",  disconnectPath: "/watch/strava/disconnect",  hint: "Gratis Entwickler-Keys unter strava.com/settings/api" },
  { id: "garmin",  name: "Garmin",       type: "credentials" as const, connectPath: "/watch/garmin/login",    disconnectPath: "/watch/garmin/disconnect",  hint: "Deine Garmin-Connect E-Mail + Passwort" },
  { id: "polar",   name: "Polar",        type: "file_upload" as const, connectPath: null,                     disconnectPath: "/watch/polar/disconnect",   hint: "GPX aus sport.polar.com exportieren" },
  { id: "apple",   name: "Apple Health", type: "file_upload" as const, connectPath: null,                     disconnectPath: "/watch/apple/disconnect",   hint: "GPX-Datei aus Health App exportieren" },
];

const FITNESS_LEVELS = ["beginner", "intermediate", "advanced"] as const;
const SPORTS = ["running", "cycling", "swimming", "triathlon"] as const;

function AchievementsSection() {
  const { achievements, isLoading } = useAchievements();
  const { t } = useI18n();

  return (
    <div className="px-5 py-5 border-b border-border">
      <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-4">{t("settings.achievements")}</p>
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
                title={a.description}
                className={`flex flex-col items-center gap-1 py-2 border border-border transition-colors ${unlocked ? "border-blue" : "opacity-30"}`}
              >
                {(() => { const Icon = ACHIEVEMENT_ICONS[a.icon] ?? Trophy; return <Icon size={22} strokeWidth={1.5} className={unlocked ? "text-blue" : ""} />; })()}
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
          {t("settings.unlockedCount", {
            count: String(achievements.filter((a) => a.unlocked_at).length),
            total: String(achievements.length),
          })}
        </p>
      )}
    </div>
  );
}

export default function EinstellungenPage() {
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const { t } = useI18n();
  const { subscription, fetchSubscription, createCheckout, openPortal, loading: billingLoading } = useBilling();

  useEffect(() => {
    fetchSubscription();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
  const [connectedProviders, setConnectedProviders] = useState<Set<string>>(new Set());
  const [stravaAvailable, setStravaAvailable] = useState(false);
  const [watchLoading, setWatchLoading] = useState(true);
  const [connectingProvider, setConnectingProvider] = useState<string | null>(null);
  const [disconnectingProvider, setDisconnectingProvider] = useState<string | null>(null);
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);
  const [providerErrors, setProviderErrors] = useState<Record<string, string>>({});
  // Garmin credential form
  const [garminEmail, setGarminEmail] = useState("");
  const [garminPassword, setGarminPassword] = useState("");
  const [garminLoading, setGarminLoading] = useState(false);
  // File upload form
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");
  const [showDeleteAccount, setShowDeleteAccount] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [goalError, setGoalError] = useState(false);
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
        const ids = new Set<string>(
          (data.connected || []).map((c: { provider: string }) => c.provider)
        );
        setConnectedProviders(ids);
        setStravaAvailable(!!data.strava_available);
      } catch {
        // ignore
      } finally {
        setWatchLoading(false);
      }
    };
    loadWatch();
  }, []);

  const handleConnect = async (p: typeof PROVIDERS[number]) => {
    if (p.type === "credentials" || p.type === "file_upload") {
      setExpandedProvider(expandedProvider === p.id ? null : p.id);
      setUploadFile(null);
      setUploadMsg("");
      setProviderErrors((prev) => ({ ...prev, [p.id]: "" }));
      return;
    }
    // OAuth (Strava)
    if (!p.connectPath) return;
    setConnectingProvider(p.id);
    setProviderErrors((prev) => ({ ...prev, [p.id]: "" }));
    try {
      const resp = await api.get(p.connectPath);
      if (resp.data.auth_url) window.location.href = resp.data.auth_url;
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "";
      setProviderErrors((prev) => ({ ...prev, [p.id]: detail || "Verbindung fehlgeschlagen." }));
    } finally {
      setConnectingProvider(null);
    }
  };

  const handleGarminLogin = async () => {
    if (!garminEmail || !garminPassword) return;
    setGarminLoading(true);
    setProviderErrors((prev) => ({ ...prev, garmin: "" }));
    try {
      await api.post("/watch/garmin/login", { email: garminEmail, password: garminPassword });
      setConnectedProviders((prev) => new Set(Array.from(prev).concat("garmin")));
      setExpandedProvider(null);
      setGarminEmail("");
      setGarminPassword("");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "";
      setProviderErrors((prev) => ({ ...prev, garmin: detail || "Login fehlgeschlagen. Prüfe E-Mail und Passwort." }));
    } finally {
      setGarminLoading(false);
    }
  };

  const handleFileUpload = async (providerId: string) => {
    if (!uploadFile) return;
    setUploadLoading(true);
    setUploadMsg("");
    try {
      const form = new FormData();
      form.append("provider", providerId);
      form.append("file", uploadFile);
      const resp = await api.post("/watch/upload-gpx", form, { headers: { "Content-Type": "multipart/form-data" } });
      setConnectedProviders((prev) => new Set(Array.from(prev).concat(providerId)));
      setUploadMsg(`✓ ${resp.data.activity_name} importiert`);
      setTimeout(() => setExpandedProvider(null), 2000);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "";
      setUploadMsg(`! ${detail || "Upload fehlgeschlagen."}`);
    } finally {
      setUploadLoading(false);
    }
  };

  const handleDisconnect = async (providerId: string, disconnectPath: string) => {
    setDisconnectingProvider(providerId);
    setProviderErrors((prev) => ({ ...prev, [providerId]: "" }));
    try {
      await api.post(disconnectPath);
      setConnectedProviders((prev) => {
        const next = new Set(prev);
        next.delete(providerId);
        return next;
      });
    } catch {
      setProviderErrors((prev) => ({ ...prev, [providerId]: "Trennen fehlgeschlagen." }));
    } finally {
      setDisconnectingProvider(null);
    }
  };

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
    setGoalError(false);
    try {
      await api.post("/user/goals", {
        sport,
        goal_description: goalDescription,
        weekly_hours: weeklyHours,
        fitness_level: fitnessLevel,
        target_date: targetDate || null,
      });
      setGoalSaved(true);
      setGoalError(false);
      setTimeout(() => setGoalSaved(false), 2000);
    } catch {
      setGoalError(true);
    } finally {
      setGoalSaving(false);
    }
  };



  const handleLogout = async () => {
    try {
      await api.post("/auth/keycloak/logout", { refresh_token: "" });
    } catch {
      // Ignore errors — local logout proceeds regardless
    }
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
      setPasswordError(t("settings.allFieldsRequired"));
      return;
    }
    if (newPassword.length < 8) {
      setPasswordError(t("settings.passwordTooShort"));
      return;
    }
    if (!newPassword.split("").some((c) => /[^a-zA-Z]/.test(c))) {
      setPasswordError(t("settings.passwordSpecialChar"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError(t("settings.passwordMismatch"));
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
      setPasswordError(t("settings.passwordChangeFailed"));
    } finally {
      setPasswordSaving(false);
    }
  };

  return (
    <div className="flex flex-col">

      {/* Header */}
      <div className="px-5 pt-5 pb-4 border-b border-border">
        <span className="font-pixel text-blue text-xl">{t("settings.title")}</span>
      </div>

      {/* Profil */}
      <div className="px-5 py-5 border-b border-border">
        <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-4">{t("settings.account")}</p>
        {profileLoading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-10 bg-border" />
            <div className="h-10 bg-border" />
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex justify-between items-center py-2 border-b border-border">
              <span className="text-xs font-sans text-textDim tracking-widest uppercase">{t("settings.email")}</span>
              <span className="text-sm font-sans text-textMain">{user?.email ?? "—"}</span>
            </div>
            {/* Name */}
            <div className="border border-border px-3 py-2">
              <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">{t("settings.name")}</p>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={100}
                className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
              />
            </div>
            {/* Geburtstag */}
            <div className="border border-border px-3 py-2">
              <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">{t("settings.birthDate")}</p>
              <input
                type="date"
                value={birthDate}
                onChange={(e) => setBirthDate(e.target.value)}
                className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
              />
            </div>
            {/* Geschlecht */}
            <div className="border border-border px-3 py-2">
              <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">{t("settings.gender")}</p>
              <select
                value={gender}
                onChange={(e) => setGender(e.target.value)}
                className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
              >
                <option value="">{t("settings.genderUnspecified")}</option>
                <option value="male">{t("settings.genderMale")}</option>
                <option value="female">{t("settings.genderFemale")}</option>
                <option value="other">{t("settings.genderOther")}</option>
              </select>
            </div>
            {/* Körperdaten */}
            <div className="grid grid-cols-2 gap-3">
              <div className="border border-border px-3 py-2">
                <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">{t("settings.weight")}</p>
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
                <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">{t("settings.height")}</p>
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
              {profileSaved ? t("settings.profileSaved") : profileSaving ? "..." : `› ${t("settings.saveProfile")}`}
            </button>
          </div>
        )}
      </div>

      {/* Ziele bearbeiten */}
      <div className="px-5 py-5 border-b border-border">
        <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-5">{t("settings.goals")}</p>

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
              <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">{t("settings.sport")}</p>
              <div className="grid grid-cols-2 gap-2">
                {SPORTS.map((id) => (
                  <button
                    key={id}
                    onClick={() => setSport(id)}
                    className={`border py-2 text-xs tracking-widest uppercase font-sans transition-colors ${
                      sport === id
                        ? "border-blue text-blue bg-blueDim"
                        : "border-border text-textDim hover:border-textDim"
                    }`}
                  >
                    {t(`sports.${id}`)}
                  </button>
                ))}
              </div>
            </div>

            {/* Ziel */}
            <div className="border border-border flex items-start px-3 py-3 gap-2">
              <span className="font-mono text-blue mt-0.5 shrink-0">›</span>
              <textarea
                placeholder={t("settings.goalPlaceholder")}
                value={goalDescription}
                onChange={(e) => setGoalDescription(e.target.value)}
                rows={2}
                className="flex-1 bg-transparent text-sm font-sans text-textMain placeholder-textDim outline-none resize-none"
              />
            </div>

            {/* Wochenstunden */}
            <div className="border border-border px-4 py-3">
              <div className="flex justify-between mb-2">
                <p className="text-xs tracking-widest uppercase text-textDim font-sans">{t("settings.weeklyHours")}</p>
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
              <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">{t("settings.fitnessLevel")}</p>
              <div className="flex gap-2">
                {FITNESS_LEVELS.map((id) => (
                  <button
                    key={id}
                    onClick={() => setFitnessLevel(id)}
                    className={`flex-1 border py-2 text-[10px] uppercase font-sans transition-colors ${
                      fitnessLevel === id
                        ? "border-blue text-blue bg-blueDim"
                        : "border-border text-textDim hover:border-textDim"
                    }`}
                  >
                    {t(`settings.${id}`)}
                  </button>
                ))}
              </div>
            </div>

            {/* Zieldatum */}
            <div className="border border-border px-4 py-3">
              <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-2">{t("settings.targetDate")}</p>
              <input
                type="date"
                value={targetDate}
                onChange={(e) => setTargetDate(e.target.value)}
                className="bg-transparent text-sm font-sans text-textMain outline-none w-full"
              />
            </div>

            {/* Speichern Button */}
            {goalError && (
              <p className="text-xs font-sans text-danger tracking-wider">! {t("settings.goalError")}</p>
            )}
            <button
              onClick={saveGoals}
              disabled={goalSaving || !goalDescription.trim()}
              className="w-full border border-blue text-blue text-xs tracking-widest uppercase font-sans py-3.5 hover:bg-blueDim transition-colors disabled:opacity-40"
            >
              {goalSaved ? (
                <span className="flex items-center justify-center gap-2">
                  <Check size={14} /> {t("settings.saved")}
                </span>
              ) : goalSaving ? t("settings.saving") : `› ${t("settings.save")}`}
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
            {PROVIDERS.map((p) => {
              const isConnected = connectedProviders.has(p.id);
              const isDisconnecting = disconnectingProvider === p.id;
              const isConnecting = connectingProvider === p.id;
              const isExpanded = expandedProvider === p.id;
              const connectLabel = p.type === "credentials" ? "Login" : p.type === "file_upload" ? "Importieren" : "Verbinden";
              const err = providerErrors[p.id];
              return (
                <div key={p.id} className="border border-border">
                  <div className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-xs tracking-widest uppercase font-sans text-textMain">{p.name}</p>
                      <p className={`text-[10px] font-sans mt-0.5 ${isConnected ? "text-blue" : "text-textDim"}`}>
                        {isConnected ? "● Verbunden" : isExpanded ? "▲ Schließen" : p.hint}
                      </p>
                    </div>
                    {isConnected ? (
                      <button
                        onClick={() => handleDisconnect(p.id, p.disconnectPath)}
                        disabled={isDisconnecting}
                        className="flex items-center gap-1.5 border border-border text-textDim text-[10px] uppercase font-sans px-2 py-1.5 hover:border-danger hover:text-danger transition-colors disabled:opacity-40"
                      >
                        <Unlink size={11} />
                        {isDisconnecting ? "..." : "Trennen"}
                      </button>
                    ) : (
                      <button
                        onClick={() => handleConnect(p)}
                        disabled={isConnecting}
                        className={`text-[10px] font-sans border px-2 py-1.5 uppercase transition-colors disabled:opacity-40 ${
                          isExpanded ? "border-border text-textDim hover:border-textMain" : "border-blue text-blue hover:bg-blueDim"
                        }`}
                      >
                        {isConnecting ? "..." : isExpanded ? "✕" : connectLabel}
                      </button>
                    )}
                  </div>
                  {/* Inline-Form */}
                  {!isConnected && isExpanded && p.type === "credentials" && (
                    <div className="border-t border-border px-4 py-4 flex flex-col gap-3">
                      <p className="text-[10px] font-sans text-textDim">Garmin-Connect Zugangsdaten. Nur Tokens werden gespeichert.</p>
                      <div className="border border-border px-3 py-2">
                        <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">E-Mail</p>
                        <input type="email" value={garminEmail} onChange={(e) => setGarminEmail(e.target.value)}
                          className="w-full bg-transparent text-sm font-sans text-textMain outline-none" autoComplete="email" />
                      </div>
                      <div className="border border-border px-3 py-2">
                        <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">Passwort</p>
                        <input type="password" value={garminPassword} onChange={(e) => setGarminPassword(e.target.value)}
                          className="w-full bg-transparent text-sm font-sans text-textMain outline-none" autoComplete="current-password"
                          onKeyDown={(e) => e.key === "Enter" && handleGarminLogin()} />
                      </div>
                      {err && <p className="text-xs font-sans text-danger">! {err}</p>}
                      <button onClick={handleGarminLogin} disabled={garminLoading || !garminEmail || !garminPassword}
                        className="w-full border border-blue text-blue text-xs uppercase tracking-widest font-sans py-2.5 hover:bg-blueDim disabled:opacity-40">
                        {garminLoading ? "Verbinde..." : "› Anmelden"}
                      </button>
                    </div>
                  )}
                  {!isConnected && isExpanded && p.type === "file_upload" && (
                    <div className="border-t border-border px-4 py-4 flex flex-col gap-3">
                      <p className="text-[10px] font-sans text-textDim">
                        {p.id === "polar"
                          ? "sport.polar.com › Training › Aktivität auswählen › Export GPX"
                          : "GPX-Datei aus iOS Health App oder kompatibler App exportieren"}
                      </p>
                      <label className="border border-border px-4 py-4 flex items-center justify-between cursor-pointer hover:border-blue transition-colors">
                        <span className="text-xs font-sans text-textDim tracking-widest uppercase truncate">{uploadFile ? uploadFile.name : "GPX / TCX wählen"}</span>
                        <span className="text-xs font-sans text-blue ml-2 shrink-0">› Auswählen</span>
                        <input type="file" accept=".gpx,.tcx,.xml" className="hidden"
                          onChange={(e) => { setUploadFile(e.target.files?.[0] ?? null); setUploadMsg(""); }} />
                      </label>
                      {uploadMsg && <p className={`text-xs font-sans ${uploadMsg.startsWith("!") ? "text-danger" : "text-blue"}`}>{uploadMsg}</p>}
                      <button onClick={() => handleFileUpload(p.id)} disabled={uploadLoading || !uploadFile}
                        className="w-full border border-blue text-blue text-xs uppercase tracking-widest font-sans py-2.5 hover:bg-blueDim disabled:opacity-40">
                        {uploadLoading ? "Wird importiert..." : "› Importieren"}
                      </button>
                    </div>
                  )}
                  {!isConnected && !isExpanded && err && (
                    <p className="px-4 pb-3 text-[10px] font-sans text-danger">! {err}</p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Achievements */}
      <AchievementsSection />

      {/* Abonnement / Billing */}
      <div className="px-5 py-5 border-b border-border">
        <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-4">{t("settings.subscription")}</p>
        {billingLoading ? (
          <div className="h-14 bg-border animate-pulse" />
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex justify-between items-center border border-border px-4 py-3">
              <div>
                <p className="text-xs tracking-widest uppercase font-sans text-textMain">
                  {subscription?.tier === "pro" ? "PRO" : subscription?.tier === "elite" ? "ELITE" : "FREE"}
                </p>
                {subscription?.expires_at && (
                  <p className="text-xs font-sans text-textDim mt-0.5">
                    {t("settings.until")} {new Date(subscription.expires_at).toLocaleDateString("de-DE")}
                  </p>
                )}
              </div>
              {subscription?.tier !== "free" && subscription?.stripe_customer_id ? (
                <button
                  onClick={openPortal}
                  disabled={billingLoading}
                  className="border border-border text-[10px] uppercase font-sans px-2 py-1.5 text-textDim hover:border-textDim transition-colors disabled:opacity-40"
                >
                  {t("settings.manage")}
                </button>
              ) : process.env.NEXT_PUBLIC_STRIPE_PRICE_PRO_MONTHLY ? (
                <button
                  onClick={() => createCheckout(process.env.NEXT_PUBLIC_STRIPE_PRICE_PRO_MONTHLY!)}
                  disabled={billingLoading}
                  className="border border-blue text-blue text-[10px] uppercase font-sans px-2 py-1.5 hover:bg-blueDim transition-colors disabled:opacity-40"
                >
                  Upgrade
                </button>
              ) : (
                <span className="text-[10px] font-sans text-textDim uppercase">Bald</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Push Notifications */}
      <PushNotificationSettings />

      {/* Language */}
      <LanguageSwitcher />

      {/* Passwort */}
      <div className="px-5 py-4 border-b border-border">
        <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-3">{t("settings.security")}</p>
        {!showPasswordForm ? (
          <div className="flex justify-between items-center">
            <div>
              <p className="text-xs font-sans text-textMain">{t("settings.password")}</p>
              <p className="text-xs font-sans text-textDim mt-0.5">••••••••</p>
            </div>
            <button
              onClick={() => setShowPasswordForm(true)}
              className="text-xs font-sans text-blue tracking-widest uppercase hover:underline"
            >
              {t("settings.changePassword")}
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {passwordSaved ? (
              <p className="text-xs font-sans text-blue tracking-widest uppercase">{t("settings.passwordSaved")}</p>
            ) : (
              <>
                <div className="border border-border px-3 py-2">
                  <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">{t("settings.currentPassword")}</p>
                  <input
                    type="password"
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
                  />
                </div>
                <div className="border border-border px-3 py-2">
                  <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">{t("settings.newPassword")}</p>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full bg-transparent text-sm font-sans text-textMain outline-none"
                  />
                </div>
                <div className="border border-border px-3 py-2">
                  <p className="text-[10px] tracking-widest uppercase text-textDim font-sans mb-1">{t("settings.confirmPassword")}</p>
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
                    {t("settings.cancel")}
                  </button>
                  <button
                    onClick={handleChangePassword}
                    disabled={passwordSaving}
                    className="flex-1 border border-blue text-blue text-xs tracking-widest uppercase font-sans py-2.5 hover:bg-blueDim transition-colors disabled:opacity-40"
                  >
                    {passwordSaving ? "..." : `› ${t("settings.save")}`}
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
          {t("settings.logout")}
        </button>
      </div>

      {/* Account löschen */}
      <div className="px-5 pb-5">
        {!showDeleteAccount ? (
          <button
            onClick={() => setShowDeleteAccount(true)}
            className="w-full text-textDim text-xs tracking-widest uppercase font-sans py-2 hover:text-danger transition-colors"
          >
            {t("settings.deleteAccount")}
          </button>
        ) : (
          <div className="border border-danger p-4">
            <p className="text-xs font-sans text-danger tracking-widest uppercase mb-3">
              ! {t("settings.deleteWarning")}
            </p>
            <p className="text-xs font-sans text-textDim mb-4">
              {t("settings.deleteDesc")}
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setShowDeleteAccount(false)}
                className="flex-1 border border-border text-textDim text-xs tracking-widest uppercase font-sans py-2.5"
              >
                {t("settings.cancel")}
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleting}
                className="flex-1 border border-danger text-danger text-xs tracking-widest uppercase font-sans py-2.5 hover:bg-red-50 transition-colors disabled:opacity-40"
              >
                {deleting ? "..." : t("settings.deleteConfirm")}
              </button>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
