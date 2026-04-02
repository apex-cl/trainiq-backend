"use client";
import { useEffect, useRef, useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export interface WatchSyncEvent {
  event: string;
  provider?: string;
  activity_date?: string;
  workout_type?: string;
  duration_min?: number;
}

/**
 * Öffnet eine persistente SSE-Verbindung zum Backend.
 * Sobald Strava/Garmin eine Aktivität synchronisiert, werden
 * Metriken und Trainingsplan automatisch neu geladen.
 *
 * Nutzt den bestehenden JWT-Token aus localStorage.
 * Reconnect mit exponential backoff bei Verbindungsabbruch.
 */
export function useWatchRealtime() {
  const qc = useQueryClient();
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelayRef = useRef(2000);
  const [lastEvent, setLastEvent] = useState<WatchSyncEvent | null>(null);

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("token");
    if (!token) return;

    // Bereits verbunden
    if (esRef.current && esRef.current.readyState !== EventSource.CLOSED) return;

    const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost/api";
    const url = `${apiBase}/tasks/watch-stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      retryDelayRef.current = 2000; // Reset backoff on success
    };

    es.onmessage = (e) => {
      try {
        const data: WatchSyncEvent = JSON.parse(e.data);
        if (data.event === "activity_synced") {
          setLastEvent(data);
          // Alle relevanten Caches invalidieren → automatisches Neu-Laden
          qc.invalidateQueries({ queryKey: ["training-week"] });
          qc.invalidateQueries({ queryKey: ["metrics-today"] });
          qc.invalidateQueries({ queryKey: ["metrics-recovery"] });
          qc.invalidateQueries({ queryKey: ["metrics-week"] });
          qc.invalidateQueries({ queryKey: ["training-stats"] });
          qc.invalidateQueries({ queryKey: ["achievements"] });
        }
      } catch {
        // Parse-Fehler ignorieren (Keepalive-Leerzeilen etc.)
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      // Exponential backoff: 2s → 4s → 8s → max 30s
      const delay = Math.min(retryDelayRef.current, 30000);
      retryDelayRef.current = delay * 2;
      retryRef.current = setTimeout(connect, delay);
    };
  }, [qc]);

  useEffect(() => {
    connect();
    return () => {
      if (retryRef.current) clearTimeout(retryRef.current);
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [connect]);

  return { lastEvent };
}
