import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api";
import { useAuth } from "../auth";
import { useBranding } from "../branding";
import { usePrefs } from "../prefs";

export default function Login() {
  const { login, loginLdap, loginDemo } = useAuth();
  const { t } = usePrefs();
  const brand = useBranding();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [useLdap, setUseLdap] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [ldapEnabled, setLdapEnabled] = useState(false);
  const [demoMode, setDemoMode] = useState(false);

  useEffect(() => {
    // Ask the server which SSO options to offer (200 with flags, no 404 probe).
    api.ssoConfig()
      .then((c) => {
        setSsoEnabled(c.oidc_enabled);
        setLdapEnabled(c.ldap_enabled);
        setDemoMode(Boolean(c.demo_mode));
        // Demo pública: se entra solo, sin teclear nada. Mucha gente abandona
        // una demo nada más ver un formulario. Si el visitante ACABA de cerrar
        // sesión no se le vuelve a meter dentro, o sería un bucle sin salida.
        let salio = false;
        try { salio = sessionStorage.getItem("rm_demo_exit") === "1"; } catch { /* modo privado */ }
        if (c.demo_mode && !salio) {
          setBusy(true);
          loginDemo().catch(() => setBusy(false));
        }
      })
      .catch(() => {});
  }, [loginDemo]);

  const entrarDemo = async () => {
    setError(null);
    setBusy(true);
    try {
      try { sessionStorage.removeItem("rm_demo_exit"); } catch { /* modo privado */ }
      await loginDemo();
    } catch {
      setError("The demo is not available right now");
      setBusy(false);
    }
  };

  const startSso = async () => {
    try {
      const r = await api.oidcLogin();
      window.location.href = r.authorization_url;
    } catch {
      setError("SSO is not available");
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (useLdap) {
        await loginLdap(email, password);
      } else {
        await login(email, password, otp || undefined);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <svg width="52" height="52" viewBox="0 0 52 52" aria-hidden className="mb-3">
            <defs>
              <linearGradient id="login-mark" x1="0" y1="1" x2="0" y2="0">
                <stop offset="0%" stopColor="#38BDF8" />
                <stop offset="45%" stopColor="#34D399" />
                <stop offset="75%" stopColor="#FBBF24" />
                <stop offset="100%" stopColor="#F87171" />
              </linearGradient>
            </defs>
            <rect x="6" y="6" width="40" height="40" rx="10" fill="none" stroke="url(#login-mark)" strokeWidth="3" />
            <rect x="22" y="14" width="8" height="24" rx="4" fill="url(#login-mark)" />
          </svg>
          <h1 className="text-xl font-semibold tracking-tight">
            {brand.product_name === "RackMon" ? (
              <>
                Rack<span className="text-accent">Mon</span>
              </>
            ) : (
              brand.product_name
            )}
          </h1>
          <p className="mt-1 text-sm text-muted">{t("appTagline")}</p>
        </div>

        {demoMode && (
          <button
            type="button"
            onClick={entrarDemo}
            disabled={busy}
            data-testid="demo-enter"
            className="btn-primary mb-4 w-full py-3 text-base font-semibold"
          >
            {busy ? "…" : t("demoEnter")}
          </button>
        )}

        <form onSubmit={onSubmit} className="panel space-y-4 p-6">
          <div>
            <label className="label">{t("email")}</label>
            <input
              className="input"
              type="email"
              aria-label="Email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div>
            <label className="label">{t("password")}</label>
            <input
              className="input"
              type="password"
              aria-label="Password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="label">{t("mfaCode")}</label>
            <input
              className="input mono"
              aria-label="Verification code"
              inputMode="numeric"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              placeholder="000000"
            />
          </div>

          {error && (
            <div className="rounded-md border border-crit/30 bg-crit/10 px-3 py-2 text-sm text-crit">
              {error}
            </div>
          )}

          {ldapEnabled && (
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={useLdap} onChange={(e) => setUseLdap(e.target.checked)} />
              {t("useLdap")}
            </label>
          )}

          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? "…" : t("signIn")}
          </button>

          {ssoEnabled && (
            <>
              <div className="flex items-center gap-3 py-1 text-xs text-muted">
                <span className="h-px flex-1 bg-border" />
                <span>or</span>
                <span className="h-px flex-1 bg-border" />
              </div>
              <button type="button" className="btn-ghost w-full border border-border" onClick={startSso}>
                {t("signInSSO")}
              </button>
            </>
          )}
        </form>

        {/* Quien lo ha hecho. Discreto, al pie, sin pedir nada: es la primera
            pantalla que ve cualquiera que instale RackMon. */}
        <p className="mt-6 text-center text-xs text-muted">
          <a
            className="transition-colors hover:text-ink"
            href="https://www.linkedin.com/in/enrique-gonz%C3%A1lez-romero-1b6a90275"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("builtBy")}
          </a>
        </p>

        {import.meta.env.DEV && (
          <p className="mt-4 text-center text-xs text-muted">
            Demo: <span className="mono">admin@rackmon.io</span> /{" "}
            <span className="mono">admin12345</span>
          </p>
        )}
      </div>
    </div>
  );
}
