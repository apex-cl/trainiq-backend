import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export function useMetrics() {
  const today = useQuery({
    queryKey: ["metrics-today"],
    queryFn: () => api.get("/metrics/today").then((r) => r.data),
    staleTime: 1000 * 60 * 10, // 10 min — metrics change at most hourly
  });

  const recovery = useQuery({
    queryKey: ["metrics-recovery"],
    queryFn: () => api.get("/metrics/recovery").then((r) => r.data),
    staleTime: 1000 * 60 * 10, // matches server-side 5-min cache + safety margin
  });

  const week = useQuery({
    queryKey: ["metrics-week"],
    queryFn: () => api.get("/metrics/week").then((r) => r.data),
    staleTime: 1000 * 60 * 30, // 30 min — weekly data is stable
  });

  return {
    today: today.data,
    recovery: recovery.data,
    week: week.data,
    isLoading: today.isLoading || recovery.isLoading || week.isLoading,
    isError: today.isError || recovery.isError || week.isError,
    refetch: () => { today.refetch(); recovery.refetch(); week.refetch(); }
  };
}
