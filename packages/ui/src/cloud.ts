// Cloud-mode helpers (Cloud Phase 2). When VITE_STETH_CLOUD=true the
// Workbench gates behind a login + sends the tenant API key with every
// request. Desktop mode (local ingestion) is unchanged.

export const cloudMode = import.meta.env.VITE_STETH_CLOUD === "true";

export type Auth = {
  token: string;
  user_id: string;
  tenant_id: string;
  email: string;
  role?: string;
  api_key: string;
  tenant_name?: string;
};

const KEY = "stethoscope.auth";

export function getAuth(): Auth | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Auth) : null;
  } catch {
    return null;
  }
}

export function setAuth(a: Auth): void {
  localStorage.setItem(KEY, JSON.stringify(a));
}

export function clearAuth(): void {
  localStorage.removeItem(KEY);
}
