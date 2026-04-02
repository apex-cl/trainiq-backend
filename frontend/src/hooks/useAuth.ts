"use client";
import { useAuthStore } from "@/store/auth";

export function useAuth() {
  const token = useAuthStore((s) => s.token);
  const storeLogout = useAuthStore((s) => s.logout);

  return { isLoggedIn: !!token, checked: true, logout: storeLogout };
}
