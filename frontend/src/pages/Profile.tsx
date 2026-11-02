import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { usePrefs } from "../prefs";

export default function Profile() {
  const { t } = usePrefs();
  const { user } = useAuth();

  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="text-lg font-semibold">{t("profile")}</h2>
      <div className="panel p-4 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-muted">{t("email")}</span>
          <span className="font-medium">{user?.email}</span>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <span className="text-muted">{t("role")}</span>
          <span className="font-medium capitalize">{user?.role}</span>
        </div>
      </div>

      <ChangePasswordCard />
      <MfaCard initiallyEnabled={!!user?.mfa_enabled} />
    </div>
  );
}

function ChangePasswordCard() {
  const { t } = usePrefs();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setMsg(null);
    if (next !== confirm) {
      setMsg({ ok: false, text: t("passwordsNoMatch") });
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(cur, next);
      setMsg({ ok: true, text: t("passwordUpdated") });
      setCur("");
      setNext("");
      setConfirm("");
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed to change password" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel space-y-3 p-4">
      <h2 className="text-sm font-semibold">{t("changePassword")}</h2>
      <div>
        <label className="label">{t("currentPassword")}</label>
        <input aria-label={t("currentPassword")} className="input" type="password" value={cur} onChange={(e) => setCur(e.target.value)} />
      </div>
      <div>
        <label className="label">{t("newPassword")}</label>
        <input aria-label={t("newPassword")} className="input" type="password" value={next} onChange={(e) => setNext(e.target.value)} />
      </div>
      <div>
        <label className="label">{t("confirm")}</label>
        <input aria-label={t("confirm")} className="input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </div>
      {msg && (
        <div className={`rounded-md px-3 py-2 text-sm ${msg.ok ? "bg-nominal/10 text-nominal" : "bg-crit/10 text-crit"}`}>
          {msg.text}
        </div>
      )}
      <button data-testid="change-password-btn" className="btn-primary" disabled={busy || !cur || !next} onClick={submit}>
        {busy ? "…" : t("changePassword")}
      </button>
    </div>
  );
}

function MfaCard({ initiallyEnabled }: { initiallyEnabled: boolean }) {
  const { t } = usePrefs();
  const [enabled, setEnabled] = useState(initiallyEnabled);
  const [setup, setSetup] = useState<{ secret: string; otpauth_url: string } | null>(null);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const begin = async () => {
    setMsg(null);
    setBusy(true);
    try {
      setSetup(await api.mfaSetup());
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    } finally {
      setBusy(false);
    }
  };

  const confirmEnable = async () => {
    if (!setup) return;
    setMsg(null);
    setBusy(true);
    try {
      const r = await api.mfaEnable(setup.secret, code);
      setEnabled(r.mfa_enabled);
      setSetup(null);
      setCode("");
      setMsg({ ok: true, text: t("mfaEnabledMsg") });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Invalid code" });
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setMsg(null);
    setBusy(true);
    try {
      const r = await api.mfaDisable(pw);
      setEnabled(r.mfa_enabled);
      setPw("");
      setMsg({ ok: true, text: t("mfaDisabledMsg") });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Wrong password" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel space-y-3 p-4" data-testid="mfa-card">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{t("twoFactor")}</h2>
        <span className={`chip ${enabled ? "text-nominal border-nominal/40" : ""}`}>{enabled ? "ON" : "OFF"}</span>
      </div>

      {!enabled && !setup && (
        <button data-testid="enable-2fa-btn" className="btn-primary" disabled={busy} onClick={begin}>
          {t("enable2fa")}
        </button>
      )}

      {!enabled && setup && (
        <div className="space-y-3">
          <p className="text-xs text-muted">{t("mfaSetupHint")}</p>
          <div className="rounded-md border border-border bg-surface2 p-3">
            <div className="text-[10px] uppercase tracking-wide text-muted">Secret</div>
            <div className="mono break-all text-sm" data-testid="mfa-secret">{setup.secret}</div>
            <div className="mt-2 text-[10px] uppercase tracking-wide text-muted">otpauth URL</div>
            <div className="mono break-all text-[11px] text-muted">{setup.otpauth_url}</div>
          </div>
          <div>
            <label className="label">{t("verificationCode")}</label>
            <input aria-label={t("verificationCode")} className="input mono" value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" />
          </div>
          <button data-testid="confirm-2fa-btn" className="btn-primary" disabled={busy || code.length < 6} onClick={confirmEnable}>
            {t("enable2fa")}
          </button>
        </div>
      )}

      {enabled && (
        <div className="space-y-3">
          <p className="text-xs text-muted">{t("mfaActive")}</p>
          <div>
            <label className="label">{t("password")}</label>
            <input aria-label={t("password")} className="input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
          </div>
          <button className="btn-danger" disabled={busy || !pw} onClick={disable}>
            {t("disable2fa")}
          </button>
        </div>
      )}

      {msg && (
        <div className={`rounded-md px-3 py-2 text-sm ${msg.ok ? "bg-nominal/10 text-nominal" : "bg-crit/10 text-crit"}`}>
          {msg.text}
        </div>
      )}
    </div>
  );
}
