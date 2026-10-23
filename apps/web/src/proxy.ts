import { NextResponse, type NextRequest } from "next/server";

// 1) /api/* is proxied same-origin to FastAPI, so the session cookie stays first-party and the
//    backend needs no CORS. The target is read at RUNTIME (not baked in at build time), so one
//    build works in compose, Easy mode, desktop local mode and behind any backend address.
// 2) Optimistic UX check only: visitors without a session cookie go to /login. Real
//    authentication and authorization happen in the FastAPI backend on every request.
const SESSION_COOKIE = "nexscout_session";

function apiOrigin(): string {
  return (process.env.NEXSCOUT_API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (pathname === "/api" || pathname.startsWith("/api/")) {
    return NextResponse.rewrite(new URL(`${apiOrigin()}${pathname}${search}`));
  }
  if (!request.cookies.has(SESSION_COOKIE)) {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/api/:path*",
    "/cases/:path*",
    "/account/:path*",
    "/approve/:path*",
    "/autopilot/:path*",
  ],
};
