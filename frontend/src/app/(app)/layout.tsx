"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { LayoutGrid, Dumbbell, MessageCircle, UtensilsCrossed, Activity, Settings } from "lucide-react";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { OfflineIndicator } from "@/components/OfflineIndicator";
import { WatchRealtimeSync } from "@/components/WatchRealtimeSync";

const tabs = [
  { href: "/dashboard",  icon: LayoutGrid },
  { href: "/training",   icon: Dumbbell },
  { href: "/chat",       icon: MessageCircle },
  { href: "/ernaehrung", icon: UtensilsCrossed },
  { href: "/metriken",   icon: Activity },
  { href: "/einstellungen", icon: Settings },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-bg flex flex-col max-w-sm mx-auto">
      <OfflineIndicator />
      <WatchRealtimeSync />
      <main className="flex-1 pb-[64px]">
        <ErrorBoundary>
          {children}
        </ErrorBoundary>
      </main>

      {/* Bottom Navigation */}
      <nav className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-sm bg-bg border-t border-border z-50">
        <div className="flex">
          {tabs.map(({ href, icon: Icon }) => {
            const isActive = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={`flex-1 flex items-center justify-center py-4 transition-colors ${
                  isActive ? "border-t-2 border-t-blue text-textMain" : "text-textDim"
                }`}
              >
                <Icon size={20} strokeWidth={1.5} />
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
