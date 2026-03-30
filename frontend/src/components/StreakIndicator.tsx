"use client";
import { Flame } from "lucide-react";
import { useStreak } from "@/hooks/useGamification";

export function StreakIndicator() {
  const { streak, isLoading } = useStreak();

  if (isLoading) return <div className="w-12 h-5 bg-[#EBEBEB] animate-pulse" />;
  if (streak.current_streak === 0) return null;

  return (
    <div className="flex items-center gap-1">
      <Flame size={14} strokeWidth={1.5} className="text-blue" />
      <span className="font-pixel text-blue" style={{ fontSize: 16 }}>
        {streak.current_streak}
      </span>
    </div>
  );
}
