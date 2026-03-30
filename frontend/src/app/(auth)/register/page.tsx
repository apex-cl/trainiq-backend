"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleKeycloakRegister = async () => {
    setError("");
    setLoading(true);
    try {
      const { data } = await api.get("/auth/keycloak-register-url");
      window.location.href = data.register_url;
    } catch {
      setError("Keycloak-Registrierung konnte nicht gestartet werden.");
      setLoading(false);
    }
  };

  const handleKeycloakLogin = async () => {
    setError("");
    setLoading(true);
    try {
      const { data } = await api.get("/auth/keycloak-login-url");
      window.location.href = data.auth_url;
    } catch {
      setError("Keycloak-Login konnte nicht gestartet werden.");
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="mb-10 text-center">
          <span className="font-pixel text-blue" style={{ fontSize: 48 }}>TRAINIQ</span>
          <p className="text-xs tracking-widest uppercase text-textDim font-sans mt-2">Konto erstellen</p>
        </div>

        {error && <p className="text-xs font-sans text-danger tracking-wider mb-4">! {error}</p>}

        <div className="flex flex-col gap-4">
          <button
            onClick={handleKeycloakRegister}
            disabled={loading}
            className="w-full border border-blue text-blue text-xs tracking-widest uppercase font-sans py-3.5 hover:bg-blueDim transition-colors disabled:opacity-50"
          >
            {loading ? "..." : "› Mit Keycloak registrieren"}
          </button>
        </div>

        <p className="text-xs font-sans text-textDim text-center mt-6">
          Schon ein Konto?{" "}
          <button onClick={handleKeycloakLogin} className="text-blue hover:underline">Einloggen</button>
        </p>
      </div>
    </div>
  );
}
