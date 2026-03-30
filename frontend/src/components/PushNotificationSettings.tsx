"use client";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { Bell, BellOff } from "lucide-react";

export function PushNotificationSettings() {
  const { permission, subscribed, loading, subscribe, unsubscribe, supported } = usePushNotifications();

  if (!supported) return null;

  return (
    <div className="px-5 py-5 border-b border-border">
      <p className="text-xs tracking-widest uppercase text-textDim font-sans mb-4">Benachrichtigungen</p>
      {loading ? (
        <div className="h-12 bg-[#EBEBEB] animate-pulse" />
      ) : (
        <div className="flex items-center justify-between border border-border px-4 py-3">
          <div className="flex items-center gap-3">
            {subscribed ? <Bell size={16} className="text-blue" /> : <BellOff size={16} className="text-textDim" />}
            <div>
              <p className="text-xs tracking-widest uppercase font-sans text-textMain">Push</p>
              <p className={`text-xs font-sans mt-0.5 ${subscribed ? "text-blue" : "text-textDim"}`}>
                {subscribed ? "● Aktiviert" : permission === "denied" ? "● Blockiert im Browser" : "○ Deaktiviert"}
              </p>
            </div>
          </div>
          {permission !== "denied" && (
            <button
              onClick={subscribed ? unsubscribe : subscribe}
              className={`border text-xs tracking-widest uppercase font-sans px-3 py-1.5 transition-colors ${
                subscribed
                  ? "border-border text-textDim hover:border-danger hover:text-danger"
                  : "border-blue text-blue hover:bg-blueDim"
              }`}
            >
              {subscribed ? "Deaktivieren" : "Aktivieren"}
            </button>
          )}
        </div>
      )}
      <p className="text-[10px] font-sans text-textDim mt-2 leading-relaxed">
        Erhalte Erinnerungen an dein Workout und Updates zu deinem Trainingsplan.
      </p>
    </div>
  );
}
