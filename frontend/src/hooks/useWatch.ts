"use client";
import { useState, useCallback, useEffect } from "react";
import api from "@/lib/api";

export interface WatchConnection {
  provider: string;
  last_synced_at: string | null;
}

export interface WatchStatus {
  connected: WatchConnection[];
  strava_available: boolean;
  garmin_available: boolean;
}

export function useWatch() {
  const [status, setStatus] = useState<WatchStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<WatchStatus>("/watch/status");
      setStatus(data);
    } catch (e) {
      setError("Status konnte nicht geladen werden");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const connectStrava = useCallback(async () => {
    try {
      const { data } = await api.get<{ auth_url: string }>("/watch/strava/connect");
      window.location.href = data.auth_url;
    } catch (e) {
      setError("Strava-Verbindung fehlgeschlagen");
    }
  }, []);

  const disconnectStrava = useCallback(async () => {
    try {
      await api.post("/watch/strava/disconnect");
      await fetchStatus();
    } catch (e) {
      setError("Trennung fehlgeschlagen");
    }
  }, [fetchStatus]);

  const connectGarmin = useCallback(async () => {
    try {
      const { data } = await api.get<{ auth_url: string }>("/watch/garmin/connect");
      window.location.href = data.auth_url;
    } catch (e) {
      setError("Garmin-Verbindung fehlgeschlagen");
    }
  }, []);

  const disconnectGarmin = useCallback(async () => {
    try {
      await api.post("/watch/garmin/disconnect");
      await fetchStatus();
    } catch (e) {
      setError("Trennung fehlgeschlagen");
    }
  }, [fetchStatus]);

  const sync = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.post<{ synced: number; provider: string | null }>("/watch/sync");
      return data;
    } catch (e) {
      setError("Synchronisation fehlgeschlagen");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const manualInput = useCallback(async (metrics: {
    hrv?: number;
    resting_hr?: number;
    sleep_duration_min?: number;
    stress_score?: number;
  }) => {
    try {
      const { data } = await api.post<{ ok: boolean }>("/watch/manual", metrics);
      return data.ok;
    } catch (e) {
      setError("Manuelle Eingabe fehlgeschlagen");
      return false;
    }
  }, []);

  return {
    status,
    loading,
    error,
    refetch: fetchStatus,
    connectStrava,
    disconnectStrava,
    connectGarmin,
    disconnectGarmin,
    sync,
    manualInput,
  };
}
