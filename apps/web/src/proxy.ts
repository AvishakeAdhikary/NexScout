import { NextResponse, type NextRequest } from "next/server";

// Optimistic UX check only: send visitors without a session cookie to /login.
// Real authentication and authorization happen in the FastAPI backend on every request.
const SESSION_COOKIE = "nexscout_session";

export function proxy(request: NextRequest) {
  if (!request.cookies.has(SESSION_COOKIE)) {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/cases/:path*", "/account/:path*"],
};
