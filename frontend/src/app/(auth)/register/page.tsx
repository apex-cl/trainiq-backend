"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";

export default function RegisterPage() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { data } = await api.post("/auth/register", { name, email, password });
      setAuth(data.access_token, data.user);
      router.push("/onboarding");
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Registrierung fehlgeschlagen.");
    } finally {
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

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="border border-border">
            <input
              type="text"
              placeholder="Dein Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoComplete="name"
              className="w-full px-4 py-3 bg-transparent text-sm font-sans text-textMain placeholder-textDim outline-none"
            />
          </div>
          <div className="border border-border">
            <input
              type="email"
              placeholder="E-Mail-Adresse"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="w-full px-4 py-3 bg-transparent text-sm font-sans text-textMain placeholder-textDim outline-none"
            />
          </div>
          <div className="border border-border">
            <input
              type="password"
              placeholder="Passwort (min. 8 Zeichen)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="new-password"
              className="w-full px-4 py-3 bg-transparent text-sm font-sans text-textMain placeholder-textDim outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full border border-blue text-blue text-xs tracking-widest uppercase font-sans py-3.5 hover:bg-blueDim transition-colors disabled:opacity-50"
          >
            {loading ? "..." : "› Konto erstellen"}
          </button>
        </form>

        <p className="text-xs font-sans text-textDim text-center mt-6">
          Schon ein Konto?{" "}
          <Link href="/login" className="text-blue hover:underline">Einloggen</Link>
        </p>
      </div>
    </div>
  );
}
