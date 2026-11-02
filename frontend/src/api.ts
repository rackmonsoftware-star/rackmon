import type {
  Alert,
  AlertRule,
  AuditEntry,
  Device,
  MetricSeries,
  Overview,
  Severity,
  TokenPair,
  User,
} from "./types";

const ACCESS_KEY = "rackmon_access";
const REFRESH_KEY = "rackmon_refresh";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface LicenseInfo {
  edition: string; // siempre "free": una sola edicion con todo
  licensee: string;
  valid: boolean;
  features: string[];
  expires_at: string | null;
  /** Dias que le quedan a la licencia. null = perpetua o sin licencia. */
  days_left?: number | null;
  max_devices: number | null;
}

export interface PublicStatus {
  title: string;
  generated_at: string;
  overall: string;
  summary: Record<string, number>;
  devices: Array<{ name: string; status: string; temperature?: number }>;
}

export interface UpdateStatus {
  current: string;
  enabled: boolean;
  channel: string;
  checked: boolean;
  latest: string | null;
  update_available: boolean;
  unsupported: boolean;
  notes: string | null;
  download_url: string | null;
  published_at: string | null;
  announcement: {
    id: string;
    level: string;
    title: string | null;
    body: string | null;
    link: string | null;
  } | null;
}

export type SupportKind = "bug" | "idea" | "question";

function getAccess(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}
function getRefresh(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}
export function setTokens(t: TokenPair): void {
  localStorage.setItem(ACCESS_KEY, t.access_token);
  localStorage.setItem(REFRESH_KEY, t.refresh_token);
}
export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}
export function hasSession(): boolean {
  return !!getAccess();
}
export function accessToken(): string | null {
  return getAccess();
}

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  const refresh = getRefresh();
  if (!refresh) return false;
  refreshInFlight = (async () => {
    try {
      const res = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!res.ok) return false;
      const data = (await res.json()) as TokenPair;
      setTokens(data);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

interface ReqOptions {
  method?: string;
  body?: unknown;
  retry?: boolean;
}

// Turn an error response body into a readable message. FastAPI sends a string
// `detail` for HTTPExceptions but an array of {loc, msg} objects for 422
// validation errors — collapse the latter to a human-readable string instead of
// a generic "Request failed" so forms can show why the request was rejected.
function extractError(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown; message?: unknown } | null)?.detail
    ?? (data as { message?: unknown } | null)?.message;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((e) => {
        const loc = Array.isArray(e?.loc) ? e.loc.filter((p: unknown) => p !== "body") : [];
        const field = loc.length ? loc[loc.length - 1] : undefined;
        const msg = typeof e?.msg === "string" ? e.msg : "invalid value";
        return field ? `${field}: ${msg}` : msg;
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return `Request failed (${status})`;
}

async function request<T>(path: string, opts: ReqOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getAccess();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(path, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  if (res.status === 401 && opts.retry !== false && getRefresh()) {
    const ok = await tryRefresh();
    if (ok) return request<T>(path, { ...opts, retry: false });
    clearTokens();
    window.dispatchEvent(new CustomEvent("rackmon:logout"));
    throw new ApiError(401, "Session expired");
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null; // non-JSON body (e.g. a proxy 502 HTML page) — don't crash
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, extractError(data, res.status));
  }
  return data as T;
}

// --- Typed endpoints ------------------------------------------------------ //
export const api = {
  // Auth
  async login(email: string, password: string, otp?: string): Promise<TokenPair> {
    const res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, otp }),
    });
    const text = await res.text();
    let data: unknown = null;
    try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON proxy error page */ }
    if (!res.ok) {
      const detail = (data as { detail?: unknown } | null)?.detail;
      throw new ApiError(res.status, typeof detail === "string" ? detail : "Login failed");
    }
    setTokens(data as TokenPair);
    return data as TokenPair;
  },
  me: () => request<User>("/api/v1/auth/me"),
  async ldapLogin(username: string, password: string): Promise<TokenPair> {
    const res = await fetch("/api/v1/auth/ldap/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const text = await res.text();
    let data: unknown = null;
    try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON proxy error page */ }
    if (!res.ok) {
      const detail = (data as { detail?: unknown } | null)?.detail;
      throw new ApiError(res.status, typeof detail === "string" ? detail : "LDAP login failed");
    }
    setTokens(data as TokenPair);
    return data as TokenPair;
  },
  async logout(): Promise<void> {
    try {
      await request<void>("/api/v1/auth/logout", { method: "POST" });
    } finally {
      clearTokens();
    }
  },

  // Overview
  overview: () => request<Overview>("/api/v1/overview"),
  license: () => request<LicenseInfo>("/api/v1/license"),
  updateStatus: () => request<UpdateStatus>("/api/v1/update-status"),
  supportConfig: () => request<{ enabled: boolean }>("/api/v1/support/config"),
  sendSupport: (message: string, email?: string, kind: SupportKind = "question") =>
    request<{ ok: boolean }>("/api/v1/support", { method: "POST", body: { message, email, kind } }),
  branding: () =>
    request<{ product_name: string; accent: string; logo_url: string | null }>("/api/v1/branding"),
  // Public status board — no auth. 404 when the admin has it switched off.
  async publicStatus(): Promise<PublicStatus> {
    const res = await fetch("/api/v1/public/status");
    if (!res.ok) throw new ApiError(res.status, "unavailable");
    const text = await res.text();
    try { return JSON.parse(text) as PublicStatus; }
    catch { throw new ApiError(502, "Service unavailable"); }
  },

  // Devices
  devices: (params?: { q?: string; tag?: string; rack?: string }) => {
    const qs = new URLSearchParams();
    if (params?.q) qs.set("q", params.q);
    if (params?.tag) qs.set("tag", params.tag);
    if (params?.rack) qs.set("rack", params.rack);
    const s = qs.toString();
    return request<Device[]>(`/api/v1/devices${s ? `?${s}` : ""}`);
  },
  device: (id: number) => request<Device>(`/api/v1/devices/${id}`),
  statuses: () => request<import("./types").DeviceStatus[]>("/api/v1/devices/status"),
  createDevice: (body: Record<string, unknown>) =>
    request<Device>("/api/v1/devices", { method: "POST", body }),
  updateDevice: (id: number, body: Record<string, unknown>) =>
    request<Device>(`/api/v1/devices/${id}`, { method: "PATCH", body }),
  deleteDevice: (id: number) =>
    request<void>(`/api/v1/devices/${id}`, { method: "DELETE" }),
  setMaintenance: (id: number, minutes: number) =>
    request<Device>(`/api/v1/devices/${id}/maintenance`, {
      method: "POST",
      body: { minutes },
    }),
  clearMaintenance: (id: number) =>
    request<Device>(`/api/v1/devices/${id}/maintenance`, { method: "DELETE" }),

  // Metrics
  series: (deviceId: number, metric: string, agg: string, from?: string, to?: string) => {
    const qs = new URLSearchParams({
      device_id: String(deviceId),
      metric,
      agg,
    });
    if (from) qs.set("from", from);
    if (to) qs.set("to", to);
    return request<MetricSeries>(`/api/v1/metrics?${qs.toString()}`);
  },
  exportUrl: (deviceId: number, metric: string, fmt: "csv" | "json") =>
    `/api/v1/metrics/export?device_id=${deviceId}&metric=${encodeURIComponent(metric)}&fmt=${fmt}`,
  anomalies: (deviceId: number, metric: string, fromIso?: string, k = 3.0) => {
    const qs = new URLSearchParams({ device_id: String(deviceId), metric, k: String(k) });
    if (fromIso) qs.set("from", fromIso);
    return request<{
      device_id: number;
      metric: string;
      unit: string;
      k: number;
      samples: number;
      count: number;
      anomalies: Array<{ time: string; value: number; z: number }>;
    }>(`/api/v1/metrics/anomalies?${qs.toString()}`);
  },
  latest: () =>
    request<
      Array<{ device_id: number; metric: string; value: number; status: number; unit: string; time: string }>
    >("/api/v1/devices/latest"),

  // Alerts
  alerts: (params?: { active?: boolean; severity?: string; device_id?: number }) => {
    const qs = new URLSearchParams();
    if (params?.active) qs.set("active", "true");
    if (params?.severity) qs.set("severity", params.severity);
    if (params?.device_id) qs.set("device_id", String(params.device_id));
    const s = qs.toString();
    return request<Alert[]>(`/api/v1/alerts${s ? `?${s}` : ""}`);
  },
  alertHistory: () => request<Alert[]>("/api/v1/alerts/history"),
  correlations: () =>
    request<{
      correlations: Array<{ rack: string; count: number; severity: Severity; alerts: Array<{ id: number; device_id: number; metric: string; severity: Severity; message: string; started_at: string }> }>;
      grouped_incidents: number;
      singletons: number;
    }>("/api/v1/alerts/correlations"),
  ackAlert: (id: number, comment: string) =>
    request<Alert>(`/api/v1/alerts/${id}/ack`, { method: "POST", body: { comment } }),
  resolveAlert: (id: number, comment: string) =>
    request<Alert>(`/api/v1/alerts/${id}/resolve`, { method: "POST", body: { comment } }),

  // Rules
  rules: () => request<AlertRule[]>("/api/v1/rules"),
  createRule: (body: Record<string, unknown>) =>
    request<AlertRule>("/api/v1/rules", { method: "POST", body }),
  updateRule: (id: number, body: Record<string, unknown>) =>
    request<AlertRule>(`/api/v1/rules/${id}`, { method: "PATCH", body }),
  deleteRule: (id: number) =>
    request<void>(`/api/v1/rules/${id}`, { method: "DELETE" }),

  // Admin
  users: () => request<User[]>("/api/v1/admin/users"),
  createUser: (body: Record<string, unknown>) =>
    request<User>("/api/v1/admin/users", { method: "POST", body }),
  updateUser: (id: number, body: Record<string, unknown>) =>
    request<User>(`/api/v1/admin/users/${id}`, { method: "PATCH", body }),
  deleteUser: (id: number) =>
    request<void>(`/api/v1/admin/users/${id}`, { method: "DELETE" }),
  audit: () => request<AuditEntry[]>("/api/v1/admin/audit"),
  getSetting: (key: string) =>
    request<{ key: string; value: Record<string, unknown> }>(`/api/v1/admin/settings/${key}`),
  putSetting: (key: string, value: Record<string, unknown>) =>
    request(`/api/v1/admin/settings/${key}`, { method: "PUT", body: { value } }),

  // Reports
  reportAdhoc: (fromIso: string, toIso: string, deviceIds?: number[]) => {
    const qs = new URLSearchParams({ from: fromIso, to: toIso, fmt: "json" });
    if (deviceIds && deviceIds.length) qs.set("device_ids", deviceIds.join(","));
    return request<{
      period: { from: string; to: string };
      alerts_by_severity: Record<string, number>;
      hottest: Array<{ device_id: number; name: string; avg_temp: number | null; max_temp: number | null; availability_pct: number; pct_over_warn: number; pct_over_crit: number; sensor?: "entrada" | "componente" }>;
      per_device: Array<{ device_id: number; name: string; samples: number; avg_temp: number | null; max_temp: number | null; availability_pct: number; pct_over_warn: number; pct_over_crit: number; sensor?: "entrada" | "componente" }>;
      device_count: number;
    }>(`/api/v1/reports/adhoc?${qs.toString()}`);
  },
  reportPdfUrl: (fromIso: string, toIso: string, deviceIds?: number[]) => {
    const qs = new URLSearchParams({ from: fromIso, to: toIso, fmt: "pdf" });
    if (deviceIds && deviceIds.length) qs.set("device_ids", deviceIds.join(","));
    return `/api/v1/reports/adhoc?${qs.toString()}`;
  },
  // SLA / availability report.
  reportSla: (fromIso: string, toIso: string, target = 99.9) => {
    const qs = new URLSearchParams({ from: fromIso, to: toIso, fmt: "json", target: String(target) });
    return request<{
      period: { from: string; to: string };
      target_pct: number;
      window_minutes: number;
      overall_availability_pct: number;
      device_count: number;
      devices_meeting_sla: number;
      total_incidents: number;
      per_device: Array<{ device_id: number; name: string; availability_pct: number; downtime_minutes: number; incidents: number; mttr_minutes: number | null; sla_met: boolean }>;
    }>(`/api/v1/reports/sla?${qs.toString()}`);
  },
  slaPdfUrl: (fromIso: string, toIso: string, target = 99.9) => {
    const qs = new URLSearchParams({ from: fromIso, to: toIso, fmt: "pdf", target: String(target) });
    return `/api/v1/reports/sla?${qs.toString()}`;
  },

  // Discovery
  discoveryScan: (target: string, community: string, snmp_version: string) =>
    request<Array<{ ip: string; sysname: string | null; vendor: string | null; already_known: boolean }>>(
      "/api/v1/discovery/scan",
      { method: "POST", body: { target, community, snmp_version } },
    ),
  discoveryImport: (devices: Array<Record<string, unknown>>) =>
    request<{ created: number[]; skipped: string[] }>("/api/v1/discovery/import", {
      method: "POST",
      body: { devices },
    }),

  // API keys
  apiKeys: () =>
    request<Array<{ id: number; name: string; prefix: string; created_at: string | null; last_used_at: string | null; revoked: boolean }>>(
      "/api/v1/admin/apikeys",
    ),
  createApiKey: (name: string) =>
    request<{ id: number; name: string; prefix: string; key: string }>("/api/v1/admin/apikeys", {
      method: "POST",
      body: { name },
    }),
  revokeApiKey: (id: number) =>
    request<void>(`/api/v1/admin/apikeys/${id}`, { method: "DELETE" }),

  // Backup / restore
  backup: () => request<{ version: number; devices: unknown[]; rules: unknown[]; settings: unknown[] }>("/api/v1/admin/backup"),
  restore: (payload: unknown) =>
    request<{ devices_created: number; devices_skipped: number; rules_created: number; rules_skipped: number; settings_restored: number }>(
      "/api/v1/admin/restore",
      { method: "POST", body: payload },
    ),

  // Templates
  templates: () =>
    request<Array<{ name: string; vendor: string; metrics: Array<{ name: string; label: string; unit: string }> }>>(
      "/api/v1/templates",
    ),
  applyTemplate: (body: Record<string, unknown>) =>
    request("/api/v1/templates/apply", { method: "POST", body }),

  // Annotations
  annotations: (deviceId: number, metric?: string, fromIso?: string) => {
    const qs = new URLSearchParams({ device_id: String(deviceId) });
    if (metric) qs.set("metric", metric);
    if (fromIso) qs.set("from", fromIso);
    return request<Array<{ id: number; device_id: number; metric: string | null; text: string; at: string; created_by: number | null }>>(
      `/api/v1/annotations?${qs.toString()}`,
    );
  },
  createAnnotation: (body: Record<string, unknown>) =>
    request("/api/v1/annotations", { method: "POST", body }),
  updateAnnotation: (id: number, text: string) =>
    request(`/api/v1/annotations/${id}`, { method: "PATCH", body: { text } }),
  deleteAnnotation: (id: number) =>
    request<void>(`/api/v1/annotations/${id}`, { method: "DELETE" }),

  // Alert snooze
  snoozeAlert: (id: number, minutes: number) =>
    request(`/api/v1/alerts/${id}/snooze?minutes=${minutes}`, { method: "POST" }),
  unsnoozeAlert: (id: number) =>
    request(`/api/v1/alerts/${id}/snooze`, { method: "DELETE" }),

  // API key rename
  renameApiKey: (id: number, name: string) =>
    request(`/api/v1/admin/apikeys/${id}`, { method: "PATCH", body: { name } }),

  // Self-service: password + MFA
  changePassword: (current_password: string, new_password: string) =>
    request("/api/v1/auth/change-password", { method: "POST", body: { current_password, new_password } }),
  mfaSetup: () => request<{ secret: string; otpauth_url: string }>("/api/v1/auth/mfa/setup", { method: "POST" }),
  mfaEnable: (secret: string, otp: string) =>
    request<{ mfa_enabled: boolean }>("/api/v1/auth/mfa/enable", { method: "POST", body: { secret, otp } }),
  mfaDisable: (password: string) =>
    request<{ mfa_enabled: boolean }>("/api/v1/auth/mfa/disable", { method: "POST", body: { password } }),

  // Notification test
  testEmail: (to: string) =>
    request<{ ok: boolean; detail: string }>(`/api/v1/admin/settings/smtp/test?to=${encodeURIComponent(to)}`, { method: "POST" }),

  // Report CSV URL
  reportCsvUrl: (fromIso: string, toIso: string, deviceIds?: number[]) => {
    const p = new URLSearchParams({ from: fromIso, to: toIso, fmt: "csv" });
    if (deviceIds && deviceIds.length) p.set("device_ids", deviceIds.join(","));
    return `/api/v1/reports/adhoc?${p.toString()}`;
  },

  // SSO
  ssoConfig: () =>
    request<{ oidc_enabled: boolean; ldap_enabled: boolean; demo_mode?: boolean }>(
      "/api/v1/auth/sso-config",
    ),
  // Entrada directa a la demo pública. Sólo existe cuando el servidor tiene
  // RACKMON_DEMO_MODE=true; en cualquier instalación normal devuelve 404.
  async demoLogin(): Promise<TokenPair> {
    const res = await fetch("/api/v1/auth/demo", { method: "POST" });
    const text = await res.text();
    let data: unknown = null;
    try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON proxy error page */ }
    if (!res.ok) {
      const detail = (data as { detail?: unknown } | null)?.detail;
      throw new ApiError(res.status, typeof detail === "string" ? detail : "Demo unavailable");
    }
    setTokens(data as TokenPair);
    return data as TokenPair;
  },
  oidcLogin: () => request<{ authorization_url: string; state: string }>("/api/v1/auth/oidc/login"),
};

/** Fetch a URL with auth and trigger a browser download. */
export async function downloadWithAuth(url: string, filename: string): Promise<void> {
  let res = await fetch(url, { headers: { Authorization: `Bearer ${accessToken()}` } });
  if (res.status === 401 && (await tryRefresh())) {
    res = await fetch(url, { headers: { Authorization: `Bearer ${accessToken()}` } });
  }
  if (!res.ok) {
    // Don't save an error body as the file — surface the failure instead.
    throw new ApiError(res.status, `Download failed (${res.status})`);
  }
  const blob = await res.blob();
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(objUrl);
}
