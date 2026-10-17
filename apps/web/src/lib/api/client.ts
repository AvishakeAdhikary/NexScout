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
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body:
        init.body === undefined
          ? undefined
          : isForm
            ? (init.body as FormData)
            : JSON.stringify(init.body),
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

// ------------------------------------------------------------------ M2: profile & documents
type S = components["schemas"];
export type FactOut = S["FactOut"];
export type Section = FactOut["section"];
export type ReviewState = FactOut["review_state"];
export type EvidenceOut = S["EvidenceOut"];
export type GapOut = S["GapOut"];
export type SnapshotOut = S["SnapshotOut"];
export type DocumentOut = S["DocumentOut"];
export type UploadOut = S["UploadOut"];
export type DocumentTextOut = S["DocumentTextOut"];
export type Preferences = S["Preferences"];
export type PreferencesOut = S["PreferencesOut"];
export type SocialProfileOut = S["SocialProfileOut"];
export type AffiliationOut = S["AffiliationOut"];
export type AffiliationFields = S["AffiliationFields"];

const c = (id: string) => `/cases/${encodeURIComponent(id)}`;
const e = encodeURIComponent;

export const factsApi = {
  list: (caseId: string, params: { section?: Section; review_state?: ReviewState } = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][],
    ).toString();
    return api<FactOut[]>(`${c(caseId)}/facts${q ? `?${q}` : ""}`);
  },
  create: (caseId: string, section: Section, data: Record<string, unknown>, isPrivate?: boolean) =>
    api<FactOut>(`${c(caseId)}/facts`, {
      method: "POST",
      body: { section, data, is_private: isPrivate ?? null },
    }),
  update: (
    id: string,
    body: {
      version: number;
      data?: Record<string, unknown>;
      is_private?: boolean;
      review_state?: ReviewState;
    },
  ) => api<FactOut>(`/facts/${e(id)}`, { method: "PATCH", body }),
  review: (caseId: string, accept: string[], reject: string[]) =>
    api<{ changed: number }>(`${c(caseId)}/facts/review`, {
      method: "POST",
      body: { accept, reject },
    }),
  merge: (caseId: string, keepId: string, mergeIds: string[]) =>
    api<FactOut>(`${c(caseId)}/facts/merge`, {
      method: "POST",
      body: { keep_id: keepId, merge_ids: mergeIds },
    }),
  remove: (id: string) => api<void>(`/facts/${e(id)}`, { method: "DELETE" }),
  evidence: (id: string) => api<EvidenceOut[]>(`/facts/${e(id)}/evidence`),
  gaps: (caseId: string) => api<GapOut[]>(`${c(caseId)}/profile/gaps`),
  snapshots: (caseId: string) => api<SnapshotOut[]>(`${c(caseId)}/snapshots`),
  snapshot: (caseId: string, reason: string) =>
    api<SnapshotOut>(`${c(caseId)}/snapshots`, { method: "POST", body: { reason } }),
};

export const documentsApi = {
  list: (caseId: string) => api<DocumentOut[]>(`${c(caseId)}/documents`),
  upload: (caseId: string, file: File, purpose: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("purpose", purpose);
    return api<UploadOut>(`${c(caseId)}/documents`, { method: "POST", body: form });
  },
  text: (id: string) => api<DocumentTextOut>(`/documents/${e(id)}/text`),
  contentUrl: (id: string) => `/api/v1/documents/${e(id)}/content`,
  remove: (id: string, deletePendingFacts: boolean) =>
    api<void>(`/documents/${e(id)}?delete_pending_facts=${deletePendingFacts}`, {
      method: "DELETE",
    }),
};

export const relationshipsApi = {
  preferences: (caseId: string) => api<PreferencesOut>(`${c(caseId)}/preferences`),
  savePreferences: (caseId: string, version: number, data: Preferences) =>
    api<PreferencesOut>(`${c(caseId)}/preferences`, { method: "PUT", body: { version, data } }),
  links: (caseId: string) => api<SocialProfileOut[]>(`${c(caseId)}/social-profiles`),
  addLink: (caseId: string, url: string, label?: string) =>
    api<SocialProfileOut>(`${c(caseId)}/social-profiles`, {
      method: "POST",
      body: { url, label: label || null },
    }),
  removeLink: (id: string) => api<void>(`/social-profiles/${e(id)}`, { method: "DELETE" }),
  affiliations: (caseId: string) => api<AffiliationOut[]>(`${c(caseId)}/affiliations`),
  createAffiliation: (caseId: string, body: AffiliationFields) =>
    api<AffiliationOut>(`${c(caseId)}/affiliations`, { method: "POST", body }),
  updateAffiliation: (id: string, body: AffiliationFields & { version: number }) =>
    api<AffiliationOut>(`/affiliations/${e(id)}`, { method: "PATCH", body }),
  removeAffiliation: (id: string) => api<void>(`/affiliations/${e(id)}`, { method: "DELETE" }),
};

export const accountApi = {
  exportUrl: "/api/v1/me/export",
  remove: (password: string) => api<void>("/me/delete", { method: "POST", body: { password } }),
};

// ------------------------------------------------------------------ M3: mind map & opportunities
export type MindMapOut = S["MindMapOut"];
export type MindNodeOut = S["MindNodeOut"];
export type MindEdgeOut = S["MindEdgeOut"];
export type SnapshotDiffOut = S["SnapshotDiffOut"];
export type SourceOut = S["SourceOut"];
// Per-source summary inside an opportunity_discovery run result (untyped JSON in the API).
export interface SyncSummaryOut {
  source_key: string;
  fetched: number;
  new_opportunities: number;
  merged_duplicates: number;
  updated: number;
  unchanged: number;
  invalid: number;
  new_for_case: number;
  skipped_reason: string | null;
}
export type OpportunityOut = S["OpportunityOut"];

export const mindmapApi = {
  get: (caseId: string) => api<MindMapOut>(`${c(caseId)}/mindmap`),
  setNode: (
    caseId: string,
    key: string,
    body: { x?: number | null; y?: number | null; hidden?: boolean; label?: string | null },
  ) =>
    api<void>(`${c(caseId)}/mindmap/nodes/${e(key)}`, { method: "PUT", body }),
  resetNode: (caseId: string, key: string) =>
    api<void>(`${c(caseId)}/mindmap/nodes/${e(key)}`, { method: "DELETE" }),
  resetAll: (caseId: string) => api<void>(`${c(caseId)}/mindmap/overrides`, { method: "DELETE" }),
  compare: (caseId: string, from: number, to: number) =>
    api<SnapshotDiffOut>(`${c(caseId)}/snapshots/compare?from_number=${from}&to_number=${to}`),
};

export const opportunitiesApi = {
  sources: () => api<SourceOut[]>("/sources"),
  configureSource: (key: string, enabled: boolean, settings: Record<string, unknown>) =>
    api<SourceOut>(`/sources/${e(key)}`, { method: "PUT", body: { enabled, settings } }),
  sync: (caseId: string) =>
    api<{ run_id: string }>(`${c(caseId)}/opportunities/sync`, { method: "POST", body: {} }),
  rescore: (caseId: string) =>
    api<{ rescored: number }>(`${c(caseId)}/opportunities/rescore`, { method: "POST" }),
  list: (caseId: string, academic: boolean) =>
    api<OpportunityOut[]>(`${c(caseId)}/opportunities?academic=${academic}`),
  setStatus: (caseId: string, id: string, status: string, version: number) =>
    api<OpportunityOut>(`${c(caseId)}/opportunities/${e(id)}`, {
      method: "PATCH",
      body: { status, version },
    }),
  report: (caseId: string, id: string, note: string) =>
    api<{ id: string }>(`${c(caseId)}/opportunities/${e(id)}/reports`, {
      method: "POST",
      body: { kind: "wrong_merge", note },
    }),
};

// ------------------------------------------------------------------ M4: runs, approvals, providers
export type RunOut = S["RunOut"];
export type StepOut = S["StepOut"];
export type ApprovalOut = S["ApprovalOut"];
export type EventOut = S["EventOut"];
export type RunDetailOut = S["RunDetailOut"];
export type WorkflowOut = S["WorkflowOut"];
export type ProviderOut = S["ProviderOut"];
export type ProviderIn = S["ProviderIn"];
export type RunAction = "pause" | "resume" | "cancel" | "retry" | "rerun" | "skip";

export const TERMINAL_RUN_STATES = new Set(["succeeded", "failed", "cancelled", "paused"]);

export const runsApi = {
  workflows: () => api<WorkflowOut[]>("/workflows"),
  start: (caseId: string, kind: string, params: Record<string, unknown> = {}) =>
    api<RunOut>(`${c(caseId)}/runs`, { method: "POST", body: { kind, params } }),
  list: (caseId: string) => api<RunOut[]>(`${c(caseId)}/runs`),
  get: (runId: string) => api<RunDetailOut>(`/runs/${e(runId)}`),
  control: (runId: string, action: RunAction, node?: string) =>
    api<RunOut>(`/runs/${e(runId)}/control`, { method: "POST", body: { action, node: node ?? null } }),
  approvals: (caseId: string) => api<ApprovalOut[]>(`${c(caseId)}/approvals`),
  decide: (approvalId: string, approve: boolean, note?: string) =>
    api<ApprovalOut>(`/approvals/${e(approvalId)}/decision`, {
      method: "POST",
      body: { approve, note: note || null },
    }),
  eventsUrl: (caseId: string) => `/api/v1${c(caseId)}/events`,
};

export type ApprovalDetailOut = S["ApprovalDetailOut"];
export const approvalsApi = {
  get: (approvalId: string) => api<ApprovalDetailOut>(`/approvals/${e(approvalId)}`),
};

export type ChannelOut = S["ChannelOut"];
export type ChannelIn = S["ChannelIn"];
export type ChannelPatch = S["ChannelPatch"];
export type ChannelCreatedOut = S["ChannelCreatedOut"];
export type DeliveryOut = S["DeliveryOut"];
export const channelsApi = {
  list: () => api<ChannelOut[]>("/channels"),
  create: (body: ChannelIn) => api<ChannelCreatedOut>("/channels", { method: "POST", body }),
  update: (id: string, body: ChannelPatch) =>
    api<ChannelOut>(`/channels/${e(id)}`, { method: "PATCH", body }),
  pair: (id: string, code: string) =>
    api<ChannelOut>(`/channels/${e(id)}/pair`, { method: "POST", body: { code } }),
  test: (id: string) => api<S["TestOut"]>(`/channels/${e(id)}/test`, { method: "POST" }),
  deliveries: (id: string) => api<DeliveryOut[]>(`/channels/${e(id)}/deliveries`),
  remove: (id: string) => api<void>(`/channels/${e(id)}`, { method: "DELETE" }),
};

export const providersApi = {
  list: () => api<ProviderOut[]>("/providers"),
  create: (body: ProviderIn) => api<ProviderOut>("/providers", { method: "POST", body }),
  remove: (id: string) => api<void>(`/providers/${e(id)}`, { method: "DELETE" }),
  verify: (id: string) =>
    api<Record<string, unknown>>(`/providers/${e(id)}/verify`, { method: "POST" }),
  setDefault: (id: string | null) =>
    api<void>("/providers/default", { method: "PUT", body: { provider_id: id } }),
};

// ------------------------------------------------------------------ M5: research, generated documents
export type ResearchOut = S["ResearchOut"];
export type FindingOut = S["FindingOut"];
export type ResearchSourceOut = S["ResearchSourceOut"];
export type DocTypeOut = S["DocTypeOut"];
export type GeneratedDocumentOut = S["GeneratedDocumentOut"];
export type GeneratedDocumentDetailOut = S["GeneratedDocumentDetailOut"];
export type VersionOut = S["VersionOut"];

export interface DraftRequest {
  doc_type: string;
  opportunity_id?: string | null;
  supervisor_finding_id?: string | null;
  affiliation_id?: string | null;
  provider_id?: string | null;
  format?: string | null;
}

export const researchApi = {
  get: (caseId: string, opportunityId: string) =>
    api<ResearchOut>(`${c(caseId)}/opportunities/${e(opportunityId)}/research`),
  start: (caseId: string, opportunityId: string) =>
    api<{ run_id: string }>(`${c(caseId)}/opportunities/${e(opportunityId)}/research`, {
      method: "POST",
    }),
  opportunity: (caseId: string, opportunityId: string) =>
    api<OpportunityOut>(`${c(caseId)}/opportunities/${e(opportunityId)}`),
  documentFormat: (caseId: string, opportunityId: string) =>
    api<S["FormatOut"]>(`${c(caseId)}/opportunities/${e(opportunityId)}/document-format`),
  referrals: (caseId: string, opportunityId: string) =>
    api<S["ReferralsOut"]>(`${c(caseId)}/opportunities/${e(opportunityId)}/referrals`),
};

export const generatedApi = {
  types: () => api<DocTypeOut[]>("/document-types"),
  formats: () => api<S["FormatOut"][]>("/document-formats"),
  draft: (caseId: string, body: DraftRequest) =>
    api<{ run_id: string }>(`${c(caseId)}/generated-documents`, { method: "POST", body }),
  list: (caseId: string, opportunityId?: string) =>
    api<GeneratedDocumentOut[]>(
      `${c(caseId)}/generated-documents${opportunityId ? `?opportunity_id=${e(opportunityId)}` : ""}`,
    ),
  get: (id: string) => api<GeneratedDocumentDetailOut>(`/generated-documents/${e(id)}`),
  version: (id: string, n: number) =>
    api<VersionOut>(`/generated-documents/${e(id)}/versions/${n}`),
  saveEdit: (id: string, markdown: string, baseVersion: number) =>
    api<GeneratedDocumentDetailOut>(`/generated-documents/${e(id)}/versions`, {
      method: "POST",
      body: { markdown, base_version: baseVersion },
    }),
  render: (id: string, version?: number) =>
    api<{ run_id: string }>(`/generated-documents/${e(id)}/render`, {
      method: "POST",
      body: { version: version ?? null },
    }),
  fileUrl: (id: string, n: number, fmt: "pdf" | "docx") =>
    `/api/v1/generated-documents/${e(id)}/versions/${n}/files/${fmt}`,
  remove: (id: string) => api<void>(`/generated-documents/${e(id)}`, { method: "DELETE" }),
};

// ------------------------------------------------------------------ M7: applications
export type ApplicationOut = S["ApplicationOut"];
export type ApplicationDetailOut = S["ApplicationDetailOut"];
export type ApplicationEventOut = S["ApplicationEventOut"];

export const applicationsApi = {
  list: (caseId: string) => api<ApplicationOut[]>(`${c(caseId)}/applications`),
  create: (caseId: string, opportunityId: string, documentIds: string[], applyUrl?: string) =>
    api<ApplicationOut>(`${c(caseId)}/applications`, {
      method: "POST",
      body: { opportunity_id: opportunityId, document_ids: documentIds, apply_url: applyUrl ?? null },
    }),
  get: (id: string) => api<ApplicationDetailOut>(`/applications/${e(id)}`),
  update: (id: string, body: Record<string, unknown> & { version: number }) =>
    api<ApplicationDetailOut>(`/applications/${e(id)}`, { method: "PATCH", body }),
  setStatus: (id: string, version: number, status: string, note?: string, reference?: string) =>
    api<ApplicationDetailOut>(`/applications/${e(id)}/status`, {
      method: "POST",
      body: { version, status, note: note || null, reference: reference || null },
    }),
  resolve: (id: string, submitted: boolean, reference?: string) =>
    api<ApplicationDetailOut>(`/applications/${e(id)}/resolve`, {
      method: "POST",
      body: { submitted, reference: reference || null },
    }),
  fill: (id: string) =>
    api<{ run_id: string }>(`/applications/${e(id)}/browser`, { method: "POST" }),
  screenshotUrl: (id: string, eventId: string) =>
    `/api/v1/applications/${e(id)}/events/${e(eventId)}/screenshot`,
};

// ------------------------------------------------------------------ M8: tracking, dashboard, chat
export type NotificationsOut = S["NotificationsOut"];
export type ReminderOut = S["ReminderOut"];
export type ChatMessageOut = S["ChatMessageOut"];

export interface DashboardOut {
  applications_by_status: Record<string, number>;
  applications_total: number;
  needs_you: { kind: string; title: string; href: string }[];
  upcoming: { kind: string; date: string; title: string; href: string }[];
  recent_runs: { id: string; title: string; status: string; created_at: string }[];
  profile: { accepted: number; pending: number; gaps: number };
  opportunities: { matches: number; shortlisted: number };
}

export interface DiagnosticsOut {
  app_version: string;
  database: string;
  workers_alive: number;
  worker_last_seen: string | null;
  worker_busy: number;
  my_tasks: { queued: number; running: number };
  recent_failures: { id: string; title: string; error: string | null; case_id: string; created_at: string }[];
  providers: { name: string; kind: string; last_check: boolean | null; checked_at: string | null }[];
}

export const trackingApi = {
  notifications: () => api<NotificationsOut>("/notifications"),
  read: (id: string) => api<void>(`/notifications/${e(id)}/read`, { method: "POST" }),
  readAll: () => api<void>("/notifications/read-all", { method: "POST" }),
  reminders: (caseId: string) => api<ReminderOut[]>(`${c(caseId)}/reminders`),
  addReminder: (caseId: string, title: string, dueOn: string, applicationId?: string) =>
    api<ReminderOut>(`${c(caseId)}/reminders`, {
      method: "POST",
      body: { title, due_on: dueOn, application_id: applicationId ?? null },
    }),
  setDone: (id: string, done: boolean) =>
    api<ReminderOut>(`/reminders/${e(id)}`, { method: "PATCH", body: { done } }),
  dashboard: (caseId: string) => api<DashboardOut>(`${c(caseId)}/dashboard`),
  diagnostics: () => api<DiagnosticsOut>("/diagnostics"),
  chatHistory: (caseId: string) => api<ChatMessageOut[]>(`${c(caseId)}/chat`),
  chat: (caseId: string, message: string) =>
    api<ChatMessageOut[]>(`${c(caseId)}/chat`, { method: "POST", body: { message } }),
  listApplications: (caseId: string, params: { status?: string; q?: string; sort?: string }) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return api<ApplicationOut[]>(`${c(caseId)}/applications${qs.size ? `?${qs}` : ""}`);
  },
  bulkStatus: (caseId: string, ids: string[], status: string) =>
    api<{ id: string; ok: boolean; error: string | null }[]>(`${c(caseId)}/applications/bulk-status`, {
      method: "POST",
      body: { ids, status },
    }),
  exportUrl: (caseId: string) => `/api/v1${c(caseId)}/applications/export.csv`,
};
