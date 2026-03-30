"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    const initSession = async () => {
      const token = localStorage.getItem("token");
      const guestToken = localStorage.getItem("guest_token");

      if (token) {
        router.replace("/dashboard");
        return;
      }

      if (guestToken) {
        try {
          const res = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL || "http://localhost/api"}/guest/session/${guestToken}`
          );
          if (res.ok) {
            router.replace("/chat");
            return;
          }
        } catch {}
      }

      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL || "http://localhost/api"}/guest/session`,
          { method: "POST" }
        );
        if (res.ok) {
          const data = await res.json();
          localStorage.setItem("guest_token", data.guest_token);
          router.replace("/chat");
          return;
        }
      } catch {}

      router.replace("/login");
    };

    initSession();
  }, [router]);

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center">
      <span className="font-pixel text-blue text-4xl">
        TRAINIQ<span className="cursor-blink">_</span>
      </span>
    </div>
  );
}
