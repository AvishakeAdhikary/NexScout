// Typed browser client for the NexScout API (same-origin via the /api rewrite).
// Authorization is enforced by the backend; this client only carries the session cookie
// and echoes the CSRF token (double-submit) on mutating requests.

import type { components } from "./schema";

export type CaseOut = components["schemas"]["CaseOut"];
export type CaseCreate = components["schemas"]["CaseCreate"];
export type CaseUpdate = components["schemas"]["CaseUpdate"];
export type UserOut = components["schemas"]["UserOut"];
export type SessionOut = components["schemas"]["SessionOut"];
export type CareerPath = CaseOut["career_path"];

const CSRF_COOKIE = "nexscout_csrf";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export interface Problem {
  status: number;
  code: string;
  detail: string;
  request_id?: string | null;
  errors?: { loc: string[]; msg: string }[];
}

export class ApiError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail);
    this.name = "ApiError";
    this.problem = problem;
  }

  get status(): number {
    return this.problem.status;
  }
}

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const match = document.cookie
    .split("; ")
    .find((part) => part.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : undefined;
}

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: "same-origin",
      signal: init.signal,
    });
  } catch {
    throw new ApiError({
      status: 0,
      code: "network_error",
      detail: "Can't reach the NexScout server. Check that it is running and try again.",
    });
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data: unknown = text ? safeJson(text) : undefined;
  if (!response.ok) {
    const problem = (data as Partial<Problem> | undefined) ?? {};
    throw new ApiError({
      status: response.status,
      code: problem.code ?? "http_error",
      detail:
        problem.detail ??
        (response.status >= 500
          ? "The server had a problem. Please try again."
          : `Request failed (${response.status}).`),
      request_id: problem.request_id,
      errors: problem.errors,
    });
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

export const authApi = {
  me: () => api<UserOut>("/auth/me"),
  login: (email: string, password: string) =>
    api<SessionOut>("/auth/login", { method: "POST", body: { email, password } }),
  register: (email: string, password: string, display_name: string) =>
    api<SessionOut>("/auth/register", {
      method: "POST",
      body: { email, password, display_name },
    }),
  logout: () => api<void>("/auth/logout", { method: "POST" }),
};

export const casesApi = {
  list: () => api<CaseOut[]>("/cases"),
  get: (id: string) => api<CaseOut>(`/cases/${encodeURIComponent(id)}`),
  create: (body: CaseCreate) => api<CaseOut>("/cases", { method: "POST", body }),
  update: (id: string, body: CaseUpdate) =>
    api<CaseOut>(`/cases/${encodeURIComponent(id)}`, { method: "PATCH", body }),
  remove: (id: string) =>
    api<void>(`/cases/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
