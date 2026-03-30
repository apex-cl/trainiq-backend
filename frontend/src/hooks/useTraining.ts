import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cachePlans, getCachedPlans, queueAction } from "@/lib/offline";

const SPORTS: Record<string, string> = {
  running: "LAUFEN", cycling: "RADFAHREN", swimming: "SCHWIMMEN", rest: "PAUSE",
};

function getDate(offsetDays: number) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().split("T")[0];
}

function getMonday(): string {
  const d = new Date();
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  d.setDate(diff);
  return d.toISOString().split("T")[0];
}

function generateEmptyWeek() {
  return Array.from({ length: 7 }, (_, i) => ({
    id: `empty-${i}`, date: getDate(i - 3), sport: "rest", workout_type: "—",
    duration_min: 0, intensity_zone: null, target_hr_min: null, target_hr_max: null,
    description: null, coach_reasoning: null, status: "planned",
  }));
}

export { SPORTS, getDate, getMonday };

export function useTraining() {
  const qc = useQueryClient();

  const week = useQuery({
    queryKey: ["training-week"],
    queryFn: async () => {
      try {
        const data = await api.get("/training/plan", { params: { week: getMonday() } }).then((r) => r.data);
        cachePlans(data).catch(() => {});
        return data;
      } catch {
        const cached = await getCachedPlans();
        if (cached.length > 0) return cached;
        return generateEmptyWeek();
      }
    },
    staleTime: 1000 * 60 * 5,
  });

  const complete = useMutation({
    mutationFn: async (id: string) => {
      try {
        await api.post(`/training/complete/${id}`);
      } catch {
        if (!navigator.onLine) {
          await queueAction({ type: "complete", endpoint: `/training/complete/${id}`, method: "POST" });
        }
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["training-week"] }),
  });

  const skip = useMutation({
    mutationFn: async ({ id, reason }: { id: string; reason: string }) => {
      try {
        await api.post(`/training/skip/${id}`, { reason });
      } catch {
        if (!navigator.onLine) {
          await queueAction({ type: "skip", endpoint: `/training/skip/${id}`, method: "POST", body: { reason } });
        }
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["training-week"] }),
  });

  const weekData = week.data ?? [];
  const today = weekData.find((p: { date: string }) => p.date === getDate(0));

  return {
    week: weekData,
    today,
    complete: complete.mutate,
    skip: skip.mutate,
    isLoading: week.isLoading,
    isError: week.isError,
    refetch: () => week.refetch()
  };
}
