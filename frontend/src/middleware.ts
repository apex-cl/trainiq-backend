import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// next-intl Middleware deaktiviert — Locale-Routing wird clientseitig gehandhabt
export function middleware(request: NextRequest) {
  // Force 200 with marker header to confirm this code runs
  const response = NextResponse.next();
  response.headers.set("x-mw-ran", "1");
  return response;
}

export const config = {
  matcher: ["/((?!api|_next|_vercel|monitoring|.*\\..*).*)"],
};
