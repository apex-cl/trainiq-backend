"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { useAuthStore } from "@/store/auth";
import { I18nProvider } from "@/hooks/useI18n";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        // Don't refetch when window regains focus — avoids waterfall on tab switch
        refetchOnWindowFocus: false,
        // Keep data in cache for 10 minutes after component unmounts
        gcTime: 1000 * 60 * 10,
      },
    },
  }));
  const init = useAuthStore((s) => s.init);

  useEffect(() => {
    init();
  }, [init]);

  useEffect(() => {
    const handler = (event: PromiseRejectionEvent) => {
      const status = event.reason?.response?.status;
      if (status && [401, 404].includes(status)) return;
      console.error("[TrainIQ] Unhandled rejection:", event.reason);
    };
    window.addEventListener("unhandledrejection", handler);
    return () => window.removeEventListener("unhandledrejection", handler);
  }, []);

  return (
    <I18nProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </I18nProvider>
  );
}
