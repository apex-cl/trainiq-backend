"use client";
import { useState, useEffect, useCallback } from "react";
import { syncQueuedActions } from "@/lib/offline";

export function useOffline() {
  const [isOffline, setIsOffline] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncCount, setSyncCount] = useState(0);

  const handleSync = useCallback(async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      const count = await syncQueuedActions();
      setSyncCount(count);
      if (count > 0) {
        setTimeout(() => setSyncCount(0), 3000);
      }
    } finally {
      setSyncing(false);
    }
  }, [syncing]);

  useEffect(() => {
    setIsOffline(!navigator.onLine);

    const handleOnline = () => {
      setIsOffline(false);
      handleSync();
    };

    const handleOffline = () => {
      setIsOffline(true);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [handleSync]);

  return { isOffline, syncing, syncCount, manualSync: handleSync };
}
