// Typed data client for the Workbench (Phase 3).
//
// Transport: HTTP/JSON to the `ref_ingest` read API (browser dev). The
// canonical transport is Tauri IPC — the command names + shapes match
// apps/desktop/src-tauri/src/commands.rs exactly, so the swap is localized
// to `call()` below (detect window.__TAURI__, use invoke()).

const BASE = (import.meta.env.VITE_STETH_API as string | undefined) ?? "http://127.0.0.1:4318";

export type Project = { id: string; name: string };

export type Trace = {
  id: string;
  project_id: string;
  label: string | null;
  status: string;
  started_at: string;
  ended_at: string | null;
  span_count: number;
  total_cost_usd: number | null;
  total_tokens_in: number | null;
  total_tokens_out: number | null;
  agent_framework: string | null;
  is_branch: boolean;
  parent_trace_id: string | null;
};

export type Span = {
  id: string;
  trace_id: string;
  parent_span_id: string | null;
  kind: string;
  name: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  status: string;
  error_message: string | null;
  cost_usd: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  tokens_cached: number | null;
  model: string | null;
  provider: string | null;
  temperature: number | null;
  prompt_hash: string | null;
  cacheable: boolean | null;
  attributes_json: string | null;
};

export type Message = {
  id: string;
  span_id: string;
  seq: number;
  role: string;
  content_inline: string | null;
  content_ref: string | null;
  tool_call_id: string | null;
};

export type ToolCall = {
  span_id: string;
  tool_name: string;
  arguments_inline: string | null;
  result_inline: string | null;
  error: string | null;
};

export type Breakpoint = {
  id: string;
  project_id: string;
  name: string | null;
  condition_dsl: string;
  enabled: boolean;
  hit_count: number;
  last_hit_at: string | null;
  last_hit_span_id: string | null;
  last_hit_trace_id: string | null;
};

// Auth headers: when cloud-mode is on and we have a session, send the
// tenant API key for tenant-scoped routes + the JWT for user-identity
// routes. Local-mode (no cloud) sends nothing extra.
function headers(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { Accept: "application/json", ...extra };
  const cloud = import.meta.env.VITE_STETH_CLOUD === "true";
  if (cloud) {
    try {
      const raw = localStorage.getItem("stethoscope.auth");
      if (raw) {
        const a = JSON.parse(raw) as { token?: string; api_key?: string };
        if (a.api_key) h["X-Stethoscope-Key"] = a.api_key;
        if (a.token) h.Authorization = `Bearer ${a.token}`;
      }
    } catch {
      /* no auth — caller will see 401 */
    }
  }
  return h;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: headers() });
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  return (await res.json()) as T;
}

export const api = {
  async health(): Promise<boolean> {
    try {
      await get<{ ok: boolean }>("/health");
      return true;
    } catch {
      return false;
    }
  },
  listProjects: () => get<Project[]>("/projects"),
  listTraces: (projectId?: string) =>
    get<Trace[]>(`/traces${projectId ? `?project_id=${projectId}` : ""}`),
  getSpans: (traceId: string) => get<Span[]>(`/traces/${traceId}/spans`),
  getSpan: (spanId: string) => get<Span | null>(`/spans/${spanId}`),
  getMessages: (spanId: string) => get<Message[]>(`/spans/${spanId}/messages`),
  getToolCall: (spanId: string) => get<ToolCall | null>(`/spans/${spanId}/tool_call`),

  listBreakpoints: () => get<Breakpoint[]>("/breakpoints"),

  addBreakpoint: (body: { condition_dsl: string; name?: string }) =>
    postJson<{ id?: string; error?: string }>("/breakpoints", body),

  deleteBreakpoint: async (id: string): Promise<void> => {
    await postJson<unknown>("/breakpoints/delete", { id });
  },

  exportTrace: (traceId: string) => get<Record<string, unknown>>(`/traces/${traceId}/export`),

  branch: (body: {
    source_trace_id: string;
    branch_point_span_id: string;
    mutation: { type: "tool_response"; span_id: string; value: string };
  }) =>
    postJson<{ ok: boolean; stdout?: string[]; stderr?: string[]; error?: string }>(
      "/branch",
      body,
    ),

  // ---- Cloud Phase 2: auth + share -------------------------------------
  signup: (body: { email: string; password: string; tenant_name?: string }) =>
    postJson<{
      token: string;
      user_id: string;
      tenant_id: string;
      tenant_name: string;
      api_key: string;
      email: string;
      detail?: string;
    }>("/auth/signup", body),

  login: (body: { email: string; password: string }) =>
    postJson<{
      token: string;
      user_id: string;
      tenant_id: string;
      email: string;
      role?: string;
      api_key: string;
      detail?: string;
    }>("/auth/login", body),

  me: () => get<{ user_id: string; tenant_id: string; role: string; exp: number }>("/auth/me"),

  createShare: (traceId: string) =>
    postJson<{ token: string; url: string; trace_id: string }>(`/traces/${traceId}/share`, {}),

  getShare: (token: string) => get<Record<string, unknown>>(`/share/${token}`),
};
