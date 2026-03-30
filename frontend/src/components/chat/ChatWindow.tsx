"use client";
import { useRef, useEffect } from "react";
import { Message } from "@/hooks/useCoach";
import { MessageBubble } from "./MessageBubble";
import { ChatLoadingSkeleton } from "@/components/ui/skeleton";

const SUGGESTIONS = [
  "Wie ist mein Recovery heute?",
  "Erstelle mir einen Trainingsplan für diese Woche",
  "Was sollte ich vor dem Training essen?"
];

export function ChatWindow({
  messages,
  loading,
  historyLoading,
  isError,
  onSuggestionClick,
}: {
  messages: Message[];
  loading: boolean;
  historyLoading: boolean;
  isError: boolean;
  onSuggestionClick?: (text: string) => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4 pb-4" style={{ paddingBottom: 160 }}>
      {historyLoading && <ChatLoadingSkeleton />}

      {messages.length === 0 && !historyLoading && (
        <div className="border border-dashed border-border p-5 mb-4">
          <p className="font-pixel text-blue text-sm mb-2">COACH BEREIT</p>
          <p className="text-sm font-sans text-textDim leading-relaxed mb-4">
            Frag mich nach deinem Plan, deiner Erholung oder Ernährung. Hier sind Vorschläge:
          </p>
          <div className="flex flex-col gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => onSuggestionClick?.(s)}
                className="text-left border border-border px-3 py-2 text-xs font-sans text-textMain hover:border-blue transition-colors"
              >
                › {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {isError && (
        <div className="border border-danger p-3 mb-2 text-center fade-up">
          <p className="text-xs font-sans text-danger uppercase tracking-widest">Coach aktuell nicht verfügbar</p>
        </div>
      )}

      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          role={msg.role}
          content={msg.content}
          created_at={msg.created_at}
        />
      ))}

      {loading && (
        <div className="flex gap-3 items-start fade-up">
          <div className="w-7 h-7 border border-border flex items-center justify-center shrink-0 mt-0.5">
            <span className="font-pixel text-blue text-xs">C</span>
          </div>
          <div className="border border-border p-3 bg-surface font-mono">
            <span className="inline-flex gap-1">
              <span className="animate-bounce">.</span>
              <span className="animate-bounce delay-100">.</span>
              <span className="animate-bounce delay-200">.</span>
            </span>
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
