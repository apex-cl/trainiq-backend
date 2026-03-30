"use client";
import { useState, useCallback, useEffect } from "react";
import api from "@/lib/api";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface GuestLimits {
  messagesRemaining: number | null;
  photosRemaining: number | null;
  isGuest: boolean;
}

export function useCoach() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [isError, setIsError] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [guestLimits, setGuestLimits] = useState<GuestLimits>({
    messagesRemaining: null,
    photosRemaining: null,
    isGuest: false,
  });

  const isGuest = typeof window !== "undefined" && !localStorage.getItem("token");

  // Gast-Limits laden
  useEffect(() => {
    if (!isGuest) return;
    const guestToken = localStorage.getItem("guest_token");
    if (!guestToken) return;

    const loadLimits = async () => {
      try {
        const res = await api.get(`/guest/session/${guestToken}`);
        setGuestLimits({
          messagesRemaining: res.data.messages_remaining,
          photosRemaining: res.data.photos_remaining,
          isGuest: true,
        });
      } catch {}
    };
    loadLimits();
  }, [isGuest]);

  // Chat-Historie beim Start laden (nur für eingeloggte User)
  useEffect(() => {
    if (isGuest) {
      setHistoryLoading(false);
      return;
    }
    const loadHistory = async () => {
      try {
        const { data } = await api.get("/coach/history");
        if (Array.isArray(data) && data.length > 0) {
          setMessages(
            data.map((m: { role: string; content: string; created_at: string }, i: number) => ({
              id: `history-${i}`,
              role: m.role as "user" | "assistant",
              content: m.content,
              created_at: m.created_at,
            }))
          );
        }
      } catch {
        // History nicht ladbar — leerer Start ist OK
      } finally {
        setHistoryLoading(false);
      }
    };
    loadHistory();
  }, [isGuest]);

  const sendMessage = useCallback(async (text: string) => {
    setIsError(false);
    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    const assistantId = (Date.now() + 1).toString();
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "", created_at: new Date().toISOString() },
    ]);

    try {
      const token = localStorage.getItem("token");
      const guestToken = localStorage.getItem("guest_token");
      const baseURL = process.env.NEXT_PUBLIC_API_URL || "http://localhost/api";
      
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      } else if (guestToken) {
        headers["X-Guest-Token"] = guestToken;
      }

      const res = await fetch(`${baseURL}/coach/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({ message: text }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 403 && err.detail?.includes("Gast-Limit")) {
          setGuestLimits((prev) => ({ ...prev, messagesRemaining: 0 }));
          throw new Error("LIMIT_REACHED");
        }
        throw new Error(err.detail || "Request failed");
      }

      // Gast-Limits aus Response-Header aktualisieren
      const remaining = res.headers.get("X-Guest-Messages-Remaining");
      if (remaining !== null) {
        setGuestLimits((prev) => ({
          ...prev,
          messagesRemaining: parseInt(remaining, 10),
        }));
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let full = "";

      if (reader) {
        let buffer = "";
        let streamDone = false;
        while (!streamDone) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

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

            if (!data || data === "[DONE]") { streamDone = true; break; }

            full += data;
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, content: full } : m))
            );
          }
        }
      }
    } catch (err: any) {
      setIsError(true);
      const errorMsg = err.message === "LIMIT_REACHED"
        ? "Gast-Limit erreicht. Bitte registrieren für mehr Nachrichten."
        : "Verbindungsfehler. Bitte versuche es erneut.";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: errorMsg }
            : m
        )
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const sendImage = useCallback(async (file: File) => {
    setIsError(false);

    // Benutzer-Nachricht mit Foto-Indikator
    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: "Foto hochgeladen — analysiere Mahlzeit...",
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    const assistantId = (Date.now() + 1).toString();
    setMessages((prev) => [
      ...prev,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        created_at: new Date().toISOString(),
      },
    ]);

    try {
      // Schritt 1: Bild zu /nutrition/upload hochladen
      const form = new FormData();
      form.append("file", file);
      form.append("meal_type", "Mahlzeit");

      const token = localStorage.getItem("token");
      const guestToken = localStorage.getItem("guest_token");
      const baseURL = process.env.NEXT_PUBLIC_API_URL || "http://localhost/api";

      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      } else if (guestToken) {
        headers["X-Guest-Token"] = guestToken;
      }

      const uploadResp = await fetch(`${baseURL}/nutrition/upload`, {
        method: "POST",
        headers,
        body: form,
      });

      if (!uploadResp.ok) {
        const err = await uploadResp.json().catch(() => ({}));
        if (uploadResp.status === 403 && err.detail?.includes("Gast-Limit")) {
          setGuestLimits((prev) => ({ ...prev, photosRemaining: 0 }));
          throw new Error("PHOTO_LIMIT_REACHED");
        }
        throw new Error("Upload fehlgeschlagen");
      }

      const analysis = await uploadResp.json();

      // Gast-Foto-Limit aktualisieren
      if (analysis.photos_remaining !== undefined) {
        setGuestLimits((prev) => ({
          ...prev,
          photosRemaining: analysis.photos_remaining,
        }));
      }

      // Kontext für den Coach aus der Analyse aufbauen
      const extraContext = [
        `Mahlzeit analysiert: ${analysis.meal_name || "Unbekannt"}`,
        `Kalorien: ${Math.round(analysis.calories || 0)} kcal`,
        `Protein: ${Math.round(analysis.protein_g || 0)}g`,
        `Kohlenhydrate: ${Math.round(analysis.carbs_g || 0)}g`,
        `Fett: ${Math.round(analysis.fat_g || 0)}g`,
        `Erkennungsgenauigkeit: ${analysis.confidence || "unbekannt"}`,
      ].join(", ");

      // Schritt 2: Coach mit Analyse-Kontext anfragen
      const coachMessage = "Ich habe gerade eine Mahlzeit fotografiert. Was hältst du davon im Kontext meines Trainings?";

      const chatHeaders: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) {
        chatHeaders["Authorization"] = `Bearer ${token}`;
      } else if (guestToken) {
        chatHeaders["X-Guest-Token"] = guestToken;
      }

      const res = await fetch(`${baseURL}/coach/chat`, {
        method: "POST",
        headers: chatHeaders,
        body: JSON.stringify({
          message: coachMessage,
          extra_context: extraContext,
        }),
      });

      // User-Nachricht auf echten Text aktualisieren
      setMessages((prev) =>
        prev.map((m) =>
          m.id === userMsg.id
            ? {
                ...m,
                content: `📷 ${analysis.meal_name || "Mahlzeit"} — ${Math.round(analysis.calories || 0)} kcal`,
              }
            : m
        )
      );

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let full = "";

      if (reader) {
        let buffer = "";
        let streamDone = false;
        while (!streamDone) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE Events aus Buffer extrahieren (getrennt durch \n\n)
          const events = buffer.split("\n\n");
          buffer = events.pop() ?? "";

          for (const event of events) {
            const dataLines = event
              .split("\n")
              .filter((l) => l.startsWith("data: "))
              .map((l) => l.slice(6));

            const data = dataLines.join("\n");

            if (!data || data === "[DONE]") { streamDone = true; break; }

            full += data;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: full } : m
              )
            );
          }
        }
      }
    } catch (err: any) {
      setIsError(true);
      const errorMsg = err.message === "PHOTO_LIMIT_REACHED"
        ? "Gast-Limit erreicht. Bitte registrieren für mehr Foto-Uploads."
        : "Bild konnte nicht analysiert werden. Bitte versuche es erneut.";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: errorMsg }
            : m
        )
      );
    } finally {
      setLoading(false);
    }
  }, []);

  return { messages, loading, historyLoading, isError, sendMessage, sendImage, guestLimits };
}
