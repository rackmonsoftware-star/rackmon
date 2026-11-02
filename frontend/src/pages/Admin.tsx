import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";

import { api, downloadWithAuth } from "../api";
import { useAuth } from "../auth";
import { usePoll } from "../hooks";
import { usePrefs } from "../prefs";
import { timeAgo } from "../lib/thermal";
import type { Role, User } from "../types";

type Tab = "users" | "audit" | "apikeys" | "backup" | "settings";

export default function Admin() {
  const { t } = usePrefs();
  const [tab, setTab] = useState<Tab>("users");
  const tabs: Array<{ key: Tab; label: string }> = [
    { key: "users", label: t("users") },
    { key: "apikeys", label: t("apiKeys") },
    { key: "backup", label: t("backup") },
    { key: "settings", label: t("settings") },
    { key: "audit", label: t("auditLog") },
  ];

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">{t("admin")}</h2>
      <div className="flex gap-1 border-b border-border">
        {tabs.map((tb) => (
          <button
            key={tb.key}
            onClick={() => setTab(tb.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
              tab === tb.key ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {tb.label}
          </button>
        ))}
      </div>
      {tab === "users" && <UsersTab />}
      {tab === "apikeys" && <ApiKeysTab />}
      {tab === "backup" && <BackupTab />}
      {tab === "settings" && <SettingsTab />}
      {tab === "audit" && <AuditTab />}
    </div>
  );
}

function UsersTab() {
  const { t } = usePrefs();
  const { user: me } = useAuth();
  const { data: users, refetch } = usePoll(() => api.users(), 20000);
  const [showCreate, setShowCreate] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);

  const changeRole = async (u: User, role: Role) => {
    await api.updateUser(u.id, { role });
    refetch();
  };
  const toggleActive = async (u: User) => {
    await api.updateUser(u.id, { is_active: !u.is_active });
    refetch();
  };
  const remove = async (u: User) => {
    if (!window.confirm(`${t("delete")} ${u.email}?`)) return;
    await api.deleteUser(u.id);
    refetch();
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => setShowCreate(true)}>
          + {t("addUser")}
        </button>
      </div>
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-3 font-medium">{t("email")}</th>
              <th className="px-4 py-3 font-medium">{t("role")}</th>
              <th className="px-4 py-3 font-medium">{t("status")}</th>
              <th className="px-4 py-3 font-medium">{t("lastSeen")}</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {(users ?? []).map((u) => {
              const self = u.id === me?.id;
              return (
                <tr key={u.id} className="border-b border-border/60">
                  <td className="px-4 py-3 text-ink">
                    {u.email}
                    {self && <span className="ml-2 chip">you</span>}
                    {u.mfa_enabled && <span className="ml-2 chip text-accent">2FA</span>}
                  </td>
                  <td className="px-4 py-3">
                    <select
                      className="input w-32 py-1"
                      value={u.role}
                      disabled={self}
                      onChange={(e) => changeRole(u, e.target.value as Role)}
                    >
                      <option value="viewer">viewer</option>
                      <option value="operator">operator</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      className={`chip ${u.is_active ? "text-nominal" : "text-crit"}`}
                      disabled={self}
                      onClick={() => toggleActive(u)}
                    >
                      {u.is_active ? "active" : "disabled"}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">{timeAgo(u.last_login_at)}</td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <button
                      data-testid="edit-user-btn"
                      className="btn-ghost text-xs"
                      onClick={() => setEditingUser(u)}
                    >
                      {t("edit")}
                    </button>
                    {!self && (
                      <button className="btn-ghost text-xs text-crit" onClick={() => remove(u)}>
                        {t("delete")}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <CreateUserModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            refetch();
          }}
        />
      )}
      {editingUser && (
        <EditUserModal
          user={editingUser}
          onClose={() => setEditingUser(null)}
          onSaved={() => {
            setEditingUser(null);
            refetch();
          }}
        />
      )}
    </div>
  );
}

function CreateUserModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = usePrefs();
  const [form, setForm] = useState({ email: "", password: "", role: "viewer" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.createUser({ email: form.email, password: form.password, role: form.role });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" className="panel w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-base font-semibold">{t("users")}</h3>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label">{t("email")}</label>
            <input aria-label={t("email")} className="input" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} required autoFocus />
          </div>
          <div>
            <label className="label">{t("password")}</label>
            <input aria-label={t("password")} className="input" type="password" value={form.password} onChange={(e) => set("password", e.target.value)} required minLength={8} />
          </div>
          <div>
            <label className="label">{t("role")}</label>
            <select aria-label={t("role")} className="input" value={form.role} onChange={(e) => set("role", e.target.value)}>
              <option value="viewer">viewer</option>
              <option value="operator">operator</option>
              <option value="admin">admin</option>
            </select>
          </div>
          {error && (
            <div className="rounded-md border border-crit/30 bg-crit/10 px-3 py-2 text-sm text-crit">{error}</div>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              {t("cancel")}
            </button>
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? "…" : t("create")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function AuditTab() {
  const { t } = usePrefs();
  const { data: entries } = usePoll(() => api.audit(), 15000);

  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
            <th className="px-4 py-3 font-medium">{t("time")}</th>
            <th className="px-4 py-3 font-medium">{t("action")}</th>
            <th className="px-4 py-3 font-medium">{t("targetCol")}</th>
            <th className="px-4 py-3 font-medium">Actor</th>
            <th className="px-4 py-3 font-medium">IP</th>
          </tr>
        </thead>
        <tbody>
          {(entries ?? []).map((e) => (
            <tr key={e.id} className="border-b border-border/60">
              <td className="px-4 py-3 text-xs text-muted">{timeAgo(e.created_at)}</td>
              <td className="px-4 py-3 mono text-ink">{e.action}</td>
              <td className="px-4 py-3 text-muted">
                {e.target_type ? `${e.target_type}${e.target_id ? ` #${e.target_id}` : ""}` : "—"}
              </td>
              <td className="px-4 py-3 text-muted">{e.actor_email ?? (e.actor_id ? `#${e.actor_id}` : "system")}</td>
              <td className="px-4 py-3 mono text-xs text-muted">{e.ip ?? "—"}</td>
            </tr>
          ))}
          {entries && entries.length === 0 && (
            <tr>
              <td colSpan={5} className="px-4 py-10 text-center text-sm text-muted">
                {t("noData")}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ApiKeysTab() {
  const { t } = usePrefs();
  const { data: keys, refetch } = usePoll(() => api.apiKeys(), 30000);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<{ name: string; key: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const res = await api.createApiKey(name.trim());
      setCreated({ name: res.name, key: res.key });
      setName("");
      refetch();
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (id: number) => {
    if (!window.confirm(`${t("revoke")}?`)) return;
    await api.revokeApiKey(id);
    refetch();
  };

  return (
    <div className="space-y-4">
      <div className="panel flex flex-wrap items-end gap-3 p-4">
        <div className="flex-1">
          <label className="label">{t("name")}</label>
          <input aria-label={t("name")} className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="grafana, script…" />
        </div>
        <button className="btn-primary" onClick={create} disabled={busy}>
          {t("createKey")}
        </button>
      </div>

      {created && (
        <div className="panel border-accent/40 p-4">
          <div className="mb-1 text-xs text-muted">{t("copyKey")}</div>
          <div className="flex items-center gap-2">
            <code className="mono flex-1 break-all rounded bg-surface2 px-3 py-2 text-ink">{created.key}</code>
            <button className="btn-ghost text-xs" onClick={() => navigator.clipboard?.writeText(created.key)}>
              {t("copy")}
            </button>
          </div>
        </div>
      )}

      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-3 font-medium">{t("name")}</th>
              <th className="px-4 py-3 font-medium">{t("prefix")}</th>
              <th className="px-4 py-3 font-medium">{t("lastUsed")}</th>
              <th className="px-4 py-3 font-medium">{t("status")}</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {(keys ?? []).map((k) => (
              <tr key={k.id} className="border-b border-border/60">
                <td className="px-4 py-3 text-ink">{k.name}</td>
                <td className="px-4 py-3 mono text-muted">{k.prefix}…</td>
                <td className="px-4 py-3 text-xs text-muted">{timeAgo(k.last_used_at)}</td>
                <td className="px-4 py-3">
                  <span className={`chip ${k.revoked ? "text-crit" : "text-nominal"}`}>
                    {k.revoked ? "revoked" : "active"}
                  </span>
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <button
                    data-testid="rename-key-btn"
                    className="btn-ghost text-xs"
                    onClick={async () => {
                      const name = window.prompt(t("rename"), k.name);
                      if (name && name.trim()) {
                        await api.renameApiKey(k.id, name.trim());
                        refetch();
                      }
                    }}
                  >
                    {t("rename")}
                  </button>
                  {!k.revoked && (
                    <button className="btn-ghost text-xs text-crit" onClick={() => revoke(k.id)}>
                      {t("revoke")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {keys && keys.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-sm text-muted">
                  {t("noData")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BackupTab() {
  const { t } = usePrefs();
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const download = () => downloadWithAuth("/api/v1/admin/backup", "rackmon_backup.json");

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setMsg(null);
    try {
      const payload = JSON.parse(await file.text());
      const res = await api.restore(payload);
      setMsg(
        `${res.devices_created} devices + ${res.rules_created} rules restored ` +
          `(${res.devices_skipped} devices skipped).`,
      );
    } catch (err) {
      setMsg(err instanceof Error ? `Error: ${err.message}` : "Restore failed");
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  return (
    <div className="panel space-y-4 p-5">
      <p className="text-sm text-muted">{t("backupDesc")}</p>
      <div className="flex flex-wrap gap-3">
        <button className="btn-primary" onClick={download}>
          {t("downloadBackup")}
        </button>
        <label className="btn-ghost cursor-pointer">
          {busy ? "…" : t("restoreBackup")}
          <input type="file" accept="application/json,.json" className="hidden" onChange={onFile} />
        </label>
      </div>
      {msg && <div className="rounded-md border border-border bg-surface2 px-3 py-2 text-sm text-ink">{msg}</div>}
    </div>
  );
}

function SettingsTab() {
  const { t } = usePrefs();
  // Report schedule
  const [repEnabled, setRepEnabled] = useState(false);
  const [repRecipients, setRepRecipients] = useState("");
  // Escalation
  const [escEnabled, setEscEnabled] = useState(false);
  const [escMinutes, setEscMinutes] = useState("15");
  const [escRecipients, setEscRecipients] = useState("");
  // Status page (Pro)
  const [spEnabled, setSpEnabled] = useState(false);
  const [spTitle, setSpTitle] = useState("System status");
  const [spTemps, setSpTemps] = useState(true);
  // Branding (white-label)
  const [brName, setBrName] = useState("");
  const [brAccent, setBrAccent] = useState("#22D3EE");
  const [brLogo, setBrLogo] = useState("");
  // Update checks (opt-in, privacy-preserving)
  const [upEnabled, setUpEnabled] = useState(false);
  const [upChannel, setUpChannel] = useState("stable");
  const [upManifest, setUpManifest] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api.getSetting("report_schedule").then((r) => {
      setRepEnabled(Boolean(r.value.enabled));
      setRepRecipients(((r.value.recipients as string[]) ?? []).join(", "));
    }).catch(() => undefined);
    api.getSetting("escalation").then((r) => {
      setEscEnabled(Boolean(r.value.enabled));
      if (r.value.after_seconds) setEscMinutes(String(Math.round(Number(r.value.after_seconds) / 60)));
      setEscRecipients(((r.value.recipients as string[]) ?? []).join(", "));
    }).catch(() => undefined);
    api.getSetting("status_page").then((r) => {
      setSpEnabled(Boolean(r.value.enabled));
      if (r.value.title) setSpTitle(String(r.value.title));
      setSpTemps(r.value.show_temperatures !== false);
    }).catch(() => undefined);
    api.getSetting("branding").then((r) => {
      if (r.value.product_name) setBrName(String(r.value.product_name));
      if (r.value.accent) setBrAccent(String(r.value.accent));
      if (r.value.logo_url) setBrLogo(String(r.value.logo_url));
    }).catch(() => undefined);
    api.getSetting("updates").then((r) => {
      setUpEnabled(Boolean(r.value.enabled));
      if (r.value.channel) setUpChannel(String(r.value.channel));
      if (r.value.manifest_url) setUpManifest(String(r.value.manifest_url));
    }).catch(() => undefined);
  }, []);

  const parseList = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

  const saveReport = async () => {
    await api.putSetting("report_schedule", { enabled: repEnabled, recipients: parseList(repRecipients) });
    setMsg(t("saved"));
  };
  const saveEsc = async () => {
    await api.putSetting("escalation", {
      enabled: escEnabled,
      after_seconds: Math.max(1, Number(escMinutes)) * 60,
      recipients: parseList(escRecipients),
    });
    setMsg(t("saved"));
  };
  const saveStatusPage = async () => {
    await api.putSetting("status_page", {
      enabled: spEnabled, title: spTitle, show_temperatures: spTemps,
    });
    setMsg(t("saved"));
  };
  const saveBranding = async () => {
    await api.putSetting("branding", {
      product_name: brName || "RackMon",
      accent: brAccent || "#22D3EE",
      logo_url: brLogo || null,
    });
    window.location.reload(); // re-fetch branding so name/logo/accent apply
  };
  const saveUpdates = async () => {
    await api.putSetting("updates", {
      enabled: upEnabled,
      channel: upChannel || "stable",
      manifest_url: upManifest.trim(),
    });
    setMsg(t("saved"));
  };

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <div className="panel space-y-3 p-5">
        <h3 className="text-sm font-semibold">{t("reports")}</h3>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input data-testid="report-enabled" type="checkbox" checked={repEnabled} onChange={(e) => setRepEnabled(e.target.checked)} />
          {t("enabled")} — {t("weeklyReportDesc")}
        </label>
        <div>
          <label className="label">{t("recipients")}</label>
          <input aria-label={t("recipients")} className="input" value={repRecipients} onChange={(e) => setRepRecipients(e.target.value)} placeholder="ops@corp.com, boss@corp.com" />
        </div>
        <div className="flex items-center gap-2">
          <button data-testid="report-save" className="btn-primary" onClick={saveReport}>{t("save")}</button>
          <button
            data-testid="test-notif-btn"
            className="btn-ghost"
            onClick={async () => {
              const to = window.prompt(t("testNotification"), repRecipients.split(",")[0]?.trim() || "");
              if (!to) return;
              try {
                const r = await api.testEmail(to);
                alert(r.detail);
              } catch {
                alert("Request failed");
              }
            }}
          >
            {t("testNotification")}
          </button>
        </div>
      </div>

      <div className="panel space-y-3 p-5">
        <h3 className="text-sm font-semibold">{t("updates")}</h3>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input data-testid="updates-enabled" type="checkbox" checked={upEnabled} onChange={(e) => setUpEnabled(e.target.checked)} />
          {t("updateChecks")}
        </label>
        <p className="text-xs text-muted">{t("updateChecksHint")}</p>
        <div className="w-40">
          <label className="label">{t("updateChannel")}</label>
          <select aria-label={t("updateChannel")} className="input" value={upChannel} onChange={(e) => setUpChannel(e.target.value)}>
            <option value="stable">stable</option>
            <option value="beta">beta</option>
          </select>
        </div>
        <div>
          <label className="label">{t("manifestUrl")}</label>
          <input aria-label={t("manifestUrl")} className="input mono" value={upManifest} onChange={(e) => setUpManifest(e.target.value)} placeholder="https://rackmon.app/updates/manifest.json" />
        </div>
        <button data-testid="updates-save" className="btn-primary" onClick={saveUpdates}>{t("save")}</button>
      </div>

      <div className="panel space-y-3 p-5">
        <h3 className="text-sm font-semibold">{t("alerts")} — {t("escalation")}</h3>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" checked={escEnabled} onChange={(e) => setEscEnabled(e.target.checked)} />
          {t("enabled")}
        </label>
        <div>
          <label className="label">{t("afterMinutes")}</label>
          <input aria-label={t("afterMinutes")} className="input mono" type="number" min={1} value={escMinutes} onChange={(e) => setEscMinutes(e.target.value)} />
        </div>
        <div>
          <label className="label">{t("recipients")}</label>
          <input aria-label={t("recipients")} className="input" value={escRecipients} onChange={(e) => setEscRecipients(e.target.value)} placeholder="oncall@corp.com" />
        </div>
        <button data-testid="esc-save" className="btn-primary" onClick={saveEsc}>{t("save")}</button>
      </div>

      <div className="panel space-y-3 p-5 lg:col-span-2">
        <h3 className="text-sm font-semibold">{t("statusPage")}</h3>
        <p className="text-xs text-muted">{t("statusPageDesc")}</p>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input data-testid="sp-enabled" type="checkbox" checked={spEnabled} onChange={(e) => setSpEnabled(e.target.checked)} />
          {t("enabled")}
        </label>
        <div>
          <label className="label">{t("pageTitle")}</label>
          <input aria-label={t("pageTitle")} className="input" value={spTitle} onChange={(e) => setSpTitle(e.target.value)} placeholder="System status" />
        </div>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" checked={spTemps} onChange={(e) => setSpTemps(e.target.checked)} />
          {t("showTemperatures")}
        </label>
        <div className="flex items-center gap-2">
          <button data-testid="sp-save" className="btn-primary" onClick={saveStatusPage}>{t("save")}</button>
          <a className="btn-ghost" href="/status" target="_blank" rel="noreferrer">{t("openPublicPage")}</a>
        </div>
      </div>

      <div className="panel space-y-3 p-5 lg:col-span-2">
        <h3 className="text-sm font-semibold">{t("branding")}</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="label">{t("productName")}</label>
            <input aria-label={t("productName")} className="input" value={brName} onChange={(e) => setBrName(e.target.value)} placeholder="RackMon" />
          </div>
          <div>
            <label className="label">{t("accentColor")}</label>
            <div className="flex items-center gap-2">
              <input
                aria-label={t("accentColor")}
                className="h-10 w-12 shrink-0 cursor-pointer rounded-md border border-border bg-surface2 p-1"
                type="color"
                value={brAccent}
                onChange={(e) => setBrAccent(e.target.value)}
              />
              <input
                className="input mono w-32"
                value={brAccent}
                onChange={(e) => setBrAccent(e.target.value)}
                placeholder="#22D3EE"
              />
            </div>
          </div>
          <div>
            <label className="label">{t("logoUrl")}</label>
            <input aria-label={t("logoUrl")} className="input" value={brLogo} onChange={(e) => setBrLogo(e.target.value)} placeholder="data:image/png;base64,… or /logo.png" />
          </div>
          <div className="sm:col-span-3">
            <button data-testid="branding-save" className="btn-primary" onClick={saveBranding}>{t("save")}</button>
          </div>
        </div>
      </div>

      {msg && (
        <div className="lg:col-span-2 rounded-md border border-nominal/30 bg-nominal/10 px-3 py-2 text-sm text-nominal">
          {msg} — note: email delivery also requires SMTP configured (env).
        </div>
      )}
    </div>
  );
}

function EditUserModal({
  user,
  onClose,
  onSaved,
}: {
  user: User;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = usePrefs();
  const [email, setEmail] = useState(user.email);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body: Record<string, unknown> = {};
      if (email && email !== user.email) body.email = email;
      if (password) body.password = password;
      if (Object.keys(body).length) await api.updateUser(user.id, body);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update user");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" className="panel w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-base font-semibold">{t("edit")} — {user.email}</h3>
        <form onSubmit={submit} className="space-y-4" data-testid="edit-user-form">
          <div>
            <label className="label">{t("email")}</label>
            <input aria-label={t("email")} className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="label">{t("resetPassword")}</label>
            <input aria-label={t("resetPassword")} className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="•••••• (unchanged)" />
          </div>
          {error && <div className="rounded-md bg-crit/10 px-3 py-2 text-sm text-crit">{error}</div>}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>{t("cancel")}</button>
            <button type="submit" className="btn-primary" disabled={busy}>{busy ? "…" : t("save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
