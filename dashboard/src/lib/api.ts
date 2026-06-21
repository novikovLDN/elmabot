import { clearToken, getToken } from "./auth";

const BASE = "/dashboard/api";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && getToken()) {
    clearToken();
    window.location.assign("/dashboard/");
    throw new ApiError(401, "Сессия истекла");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = (j && (j.detail || j.error)) || detail;
    } catch {
      /* non-json error */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
};

// --- Response types -------------------------------------------------------

export type Windows = Record<string, number>;

export interface StatsUsers {
  users_total: number; users_today: number; users_reachable: number;
  activated_total: number; trials_used: number; buyers: number;
  subs_active: number; payments_paid: number;
  revenue_total: number; revenue_today: number;
}
export interface Health {
  active_total: number; active_trial: number; active_paid: number;
  paying_users: number; payments_paid: number; trials_used: number; users_total: number;
}
export interface Overview {
  users: StatsUsers; health: Health; revenue: Windows; activity: Windows;
}
export interface DailyPoint {
  day: string; revenue: number; payments: number;
  new_users: number; new_subs: number; new_paid_subs: number;
}
export interface HourlyPoint {
  hour: number; revenue: number; payments: number;
  new_users: number; new_subs: number; new_paid_subs: number;
}
export interface Series<T> { days: number; series: T[]; }
export interface ProviderRow { provider: string; payments: number; revenue: number; }
export interface BreakdownRow { tariff_code: string; payments: number; revenue: number; }

export interface Paged<T> { items: T[]; total: number; page: number; limit: number; }

export interface UserRow {
  telegram_id: number; username: string | null; created_at: string;
  is_reachable: boolean; trial_used_at: string | null; referred_by: number | null;
  sub_status: string | null; sub_source: string | null; expires_at: string | null;
  payments_paid: number;
}
export interface UserDetail {
  user: Record<string, unknown>;
  payments: Array<Record<string, unknown>>;
  referral: { invited: number; purchased: number };
}
export interface PaymentRow {
  telegram_id: number; username: string | null; amount_kopecks: number;
  provider: string; status: string; tariff_code: string | null;
  fail_reason: string | null; created_at: string; paid_at: string | null;
}
export interface ReferralRow {
  referrer_id: number; username: string | null; invited: number; purchased: number;
}
export interface GiftRow {
  code: string; tariff_code: string; status: string;
  created_by: number; redeemed_by: number | null;
  created_at: string; redeemed_at: string | null;
  created_by_username: string | null; redeemed_by_username: string | null;
}
export interface AuditRow {
  id: number; admin_id: number; action: string; target_id: number | null;
  detail: string | null; created_at: string; target_username: string | null;
}
export interface Segment { key: string; label: string; count: number; }
export interface Settings {
  admin: { telegram_id: number; username: string | null };
  brand: string; trial_days: number; device_limit: number;
  referral_bonus_days: number; payments_enabled: boolean;
  dashboard_base_url: string;
  tariffs: Array<{ code: string; title: string; price_rub: number; days: number; save_label: string | null }>;
  passkeys: Array<{ credential_id: string; label: string | null; created_at: string; last_used_at: string | null }>;
}

// --- Endpoints ------------------------------------------------------------

export const endpoints = {
  // auth
  login: (password: string, telegram_id?: number) =>
    api.post<{ token: string; telegram_id: number }>("/auth/login", { password, telegram_id }),
  setupCheck: (token: string) =>
    api.get<{ valid: boolean; telegram_id?: number }>(`/auth/setup/${token}`),
  setup: (token: string, password: string) =>
    api.post<{ token: string; telegram_id: number }>("/auth/setup", { token, password }),
  me: () => api.get<{ telegram_id: number; username: string | null }>("/auth/me"),

  // passkey / webauthn
  passkeyAvailable: () =>
    api.get<{ available: boolean; enabled: boolean }>("/auth/passkey/available"),
  passkeyRegisterBegin: () =>
    api.post<Record<string, unknown>>("/auth/passkey/register/begin", {}),
  passkeyRegisterComplete: (credential: unknown, label?: string) =>
    api.post<{ ok: boolean }>("/auth/passkey/register/complete", { credential, label }),
  passkeyLoginBegin: () =>
    api.post<{ flow_id: string; options: Record<string, unknown> }>("/auth/passkey/login/begin", {}),
  passkeyLoginComplete: (flow_id: string, credential: unknown) =>
    api.post<{ token: string; telegram_id: number }>("/auth/passkey/login/complete", { flow_id, credential }),
  passkeyDelete: (credential_id: string) =>
    api.post<{ ok: boolean }>("/settings/passkeys/delete", { credential_id }),

  // stats
  overview: () => api.get<Overview>("/stats/overview"),
  daily: (days = 30) => api.get<Series<DailyPoint>>(`/stats/daily?days=${days}`),
  hourly: (days = 7) => api.get<Series<HourlyPoint>>(`/stats/hourly?days=${days}`),
  providers: (hours = 24 * 30) => api.get<ProviderRow[]>(`/stats/providers?hours=${hours}`),
  breakdown: (hours = 24 * 30) => api.get<BreakdownRow[]>(`/stats/breakdown?hours=${hours}`),

  // users
  users: (q: string, page: number, limit = 25) =>
    api.get<Paged<UserRow>>(`/users?q=${encodeURIComponent(q)}&page=${page}&limit=${limit}`),
  user: (tg: number) => api.get<UserDetail>(`/users/${tg}`),
  grant: (tg: number, days: number) => api.post<{ ok: boolean }>(`/users/${tg}/grant`, { days }),
  revoke: (tg: number) => api.post<{ ok: boolean }>(`/users/${tg}/revoke`),

  // payments
  payments: (page: number, limit = 30) =>
    api.get<Paged<PaymentRow>>(`/payments?page=${page}&limit=${limit}`),
  paymentsByProvider: (hours = 24 * 30) =>
    api.get<ProviderRow[]>(`/payments/by-provider?hours=${hours}`),

  // referrals
  referralsOverall: () =>
    api.get<{ total: number; credited: number; referrers: number }>("/referrals/overall"),
  referralsTop: (page: number, limit = 25) =>
    api.get<Paged<ReferralRow>>(`/referrals/top?page=${page}&limit=${limit}`),

  // gifts / audit
  gifts: (page: number, limit = 30) => api.get<Paged<GiftRow>>(`/gifts?page=${page}&limit=${limit}`),
  audit: (page: number, limit = 50) => api.get<Paged<AuditRow>>(`/audit?page=${page}&limit=${limit}`),

  // broadcasts
  segments: () => api.get<Segment[]>("/broadcasts/segments"),
  broadcastTestSelf: (payload: BroadcastPayload) =>
    api.post<{ ok: boolean }>("/broadcasts/test-self", payload),
  broadcastSend: (payload: BroadcastPayload) =>
    api.post<{ ok: boolean; total: number }>("/broadcasts", payload),

  // settings
  settings: () => api.get<Settings>("/settings"),
};

export interface BroadcastPayload {
  segment?: string;
  text: string;
  photo_file_id?: string;
  button_text?: string;
  button_url?: string;
}
