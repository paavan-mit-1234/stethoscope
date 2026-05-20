import { useState } from "react";
import { setAuth } from "../cloud";
import { api } from "../data/api";

// Cloud-mode login wall (Cloud Phase 2). Same Win2000 aesthetic as the
// branch modal. Hidden entirely in desktop mode.

const inputStyle: React.CSSProperties = {
  width: "100%",
  font: "inherit",
  background: "var(--canvas)",
  padding: "3px 5px",
  outline: "none",
  border: "none",
};

export function LoginModal() {
  const [mode, setMode] = useState<"signup" | "login">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenant, setTenant] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r =
        mode === "signup"
          ? await api.signup({ email, password, tenant_name: tenant || undefined })
          : await api.login({ email, password });
      if ("detail" in r && r.detail) {
        setErr(r.detail);
        return;
      }
      setAuth({
        token: r.token,
        user_id: r.user_id,
        tenant_id: r.tenant_id,
        email: r.email,
        api_key: r.api_key,
        role: "role" in r ? r.role : undefined,
        tenant_name: "tenant_name" in r ? r.tenant_name : undefined,
      });
      location.reload();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "#000",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        className="raised-2"
        style={{ width: 380, background: "var(--window-bg)" }}
        onKeyDown={(e) => e.key === "Enter" && !busy && submit()}
      >
        <div className="pane-title">
          <span>Stethoscope Cloud — {mode === "signup" ? "Sign up" : "Log in"}</span>
        </div>
        <div style={{ display: "flex", gap: 2, padding: "3px 3px 0", background: "var(--chrome)" }}>
          {(["signup", "login"] as const).map((m) => (
            <button
              key={m}
              className="btn"
              onClick={() => setMode(m)}
              style={{
                transform: m === mode ? "translateY(-1px)" : undefined,
                background: m === mode ? "var(--canvas)" : "var(--chrome)",
              }}
            >
              {m === "signup" ? "Sign up" : "Log in"}
            </button>
          ))}
        </div>
        <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
          <label>
            email:
            <input
              className="sunken"
              style={inputStyle}
              value={email}
              autoFocus
              onChange={(e) => setEmail(e.target.value)}
              spellCheck={false}
            />
          </label>
          <label>
            password (min 8):
            <input
              className="sunken"
              type="password"
              style={inputStyle}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {mode === "signup" && (
            <label>
              tenant name (optional):
              <input
                className="sunken"
                style={inputStyle}
                value={tenant}
                onChange={(e) => setTenant(e.target.value)}
                placeholder="(defaults to your email prefix)"
              />
            </label>
          )}
          {err && <div style={{ color: "var(--signal-red)" }}>{err}</div>}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <button className="btn" disabled={busy} onClick={submit}>
              {busy ? "[████████░░] …" : "OK"}
            </button>
          </div>
          <div style={{ color: "var(--chrome-dark)", fontSize: 12 }}>
            Signup also provisions your tenant + an OTLP API key. Agents ship
            traces with that key (X-Stethoscope-Key); the UI uses it
            alongside your session JWT.
          </div>
        </div>
      </div>
    </div>
  );
}
