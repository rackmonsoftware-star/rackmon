import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { useAuth } from "../auth";
import { usePoll } from "../hooks";
import { usePrefs } from "../prefs";
import { SEVERITY_COLOR, formatAlertValue, timeAgo } from "../lib/thermal";
import type { Alert, AlertRule } from "../types";

type Tab = "active" | "history" | "rules";

export default function Alerts() {
  const { t } = usePrefs();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("active");

  const tabs: Array<{ key: Tab; label: string }> = [
    { key: "active", label: t("active") },
    { key: "history", label: t("history") },
    { key: "rules", label: t("rules") },
  ];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("alerts")}</h2>
      </div>

      <div className="flex gap-1 border-b border-border">
        {tabs.map((tb) => (
          <button
            key={tb.key}
            onClick={() => setTab(tb.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
              tab === tb.key
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {tab === "active" && <ActiveTab canAct={can("operator")} />}
      {tab === "history" && <HistoryTab />}
      {tab === "rules" && <RulesTab canEdit={can("operator")} />}
    </div>
  );
}

function ActiveTab({ canAct }: { canAct: boolean }) {
  const { t } = usePrefs();
  const navigate = useNavigate();
  const { data: alerts, refetch } = usePoll(() => api.alerts({ active: true }), 5000);
  const { data: corr } = usePoll(() => api.correlations(), 8000);

  const act = async (a: Alert, kind: "ack" | "resolve") => {
    const comment = window.prompt(`${kind === "ack" ? t("acknowledge") : t("resolve")} — ${t("comment")}:`);
    if (!comment) return;
    if (kind === "ack") await api.ackAlert(a.id, comment);
    else await api.resolveAlert(a.id, comment);
    refetch();
  };

  const snooze = async (a: Alert) => {
    if (a.snoozed_until && new Date(a.snoozed_until).getTime() > Date.now()) {
      await api.unsnoozeAlert(a.id);
    } else {
      await api.snoozeAlert(a.id, 60);
    }
    refetch();
  };

  if (!alerts) return <div className="p-4 text-sm text-muted">{t("loading")}</div>;
  if (alerts.length === 0)
    return (
      <div className="panel p-8 text-center text-sm text-nominal">{t("noAlerts")}</div>
    );

  return (
    <div className="space-y-2">
      {corr && corr.correlations.length > 0 && (
        <div className="panel border-crit/30 p-4">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-crit">
            {t("incidents")}
          </div>
          <div className="space-y-1.5">
            {corr.correlations.map((g) => (
              <div key={g.rack} className="flex items-center gap-2 text-sm">
                <span className="h-2 w-2 rounded-full" style={{ background: SEVERITY_COLOR[g.severity] }} />
                <span className="font-medium text-ink">{g.rack}</span>
                <span className="text-muted">— {g.count} {t("relatedAlerts")}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {alerts.map((a) => (
        <div key={a.id} className="panel flex items-center gap-3 px-4 py-3">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SEVERITY_COLOR[a.severity] }} />
          <button className="min-w-0 flex-1 text-left" onClick={() => navigate(`/devices/${a.device_id}`)}>
            <div className="truncate text-sm text-ink">{a.message}</div>
            <div className="text-xs text-muted">
              {timeAgo(a.started_at)} · {a.metric} · {formatAlertValue(a.metric, a.value)}
            </div>
          </button>
          <span className="chip capitalize" style={{ color: SEVERITY_COLOR[a.severity] }}>
            {a.state}
          </span>
          {a.snoozed_until && new Date(a.snoozed_until).getTime() > Date.now() && (
            <span className="chip text-warn" title={new Date(a.snoozed_until).toLocaleString()}>
              {t("snoozed")}
            </span>
          )}
          {canAct && (
            <div className="flex gap-1">
              {a.state === "firing" && (
                <button className="btn-ghost text-xs" onClick={() => act(a, "ack")}>
                  {t("acknowledge")}
                </button>
              )}
              <button data-testid="snooze-btn" className="btn-ghost text-xs" onClick={() => snooze(a)}>
                {t("snooze")}
              </button>
              <button className="btn-ghost text-xs" onClick={() => act(a, "resolve")}>
                {t("resolve")}
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function HistoryTab() {
  const { t } = usePrefs();
  const navigate = useNavigate();
  const { data: history } = usePoll(() => api.alertHistory(), 15000);

  if (!history) return <div className="p-4 text-sm text-muted">{t("loading")}</div>;

  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
            <th className="px-4 py-3 font-medium">{t("severity")}</th>
            <th className="px-4 py-3 font-medium">Message</th>
            <th className="px-4 py-3 font-medium">{t("metric")}</th>
            <th className="px-4 py-3 font-medium">State</th>
            <th className="px-4 py-3 font-medium">Started</th>
            <th className="px-4 py-3 font-medium">Ended</th>
          </tr>
        </thead>
        <tbody>
          {history.map((a) => (
            <tr
              key={a.id}
              tabIndex={0}
              role="link"
              aria-label={`Alert on device ${a.device_id}`}
              className="cursor-pointer border-b border-border/60 hover:bg-surface2/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              onClick={() => navigate(`/devices/${a.device_id}`)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navigate(`/devices/${a.device_id}`); } }}
            >
              <td className="px-4 py-3">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: SEVERITY_COLOR[a.severity] }} />
                  <span className="capitalize text-muted">{a.severity}</span>
                </span>
              </td>
              <td className="max-w-xs truncate px-4 py-3 text-ink">{a.message}</td>
              <td className="px-4 py-3 mono text-muted">{a.metric}</td>
              <td className="px-4 py-3 capitalize text-muted">{a.state}</td>
              <td className="px-4 py-3 text-xs text-muted">{timeAgo(a.started_at)}</td>
              <td className="px-4 py-3 text-xs text-muted">{a.ended_at ? timeAgo(a.ended_at) : "—"}</td>
            </tr>
          ))}
          {history.length === 0 && (
            <tr>
              <td colSpan={6} className="px-4 py-10 text-center text-sm text-muted">
                {t("noData")}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function RulesTab({ canEdit }: { canEdit: boolean }) {
  const { t } = usePrefs();
  const { data: rules, refetch } = usePoll(() => api.rules(), 15000);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<AlertRule | null>(null);

  const toggle = async (r: AlertRule) => {
    await api.updateRule(r.id, { enabled: !r.enabled });
    refetch();
  };
  const remove = async (r: AlertRule) => {
    if (!window.confirm(`${t("delete")} "${r.name}"?`)) return;
    await api.deleteRule(r.id);
    refetch();
  };

  return (
    <div className="space-y-4">
      {canEdit && (
        <div className="flex justify-end">
          <button className="btn-primary" onClick={() => setShowCreate(true)}>
            + {t("create")}
          </button>
        </div>
      )}
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-3 font-medium">{t("name")}</th>
              <th className="px-4 py-3 font-medium">{t("scope")}</th>
              <th className="px-4 py-3 font-medium">{t("condition")}</th>
              <th className="px-4 py-3 font-medium">{t("severity")}</th>
              <th className="px-4 py-3 font-medium">{t("status")}</th>
              {canEdit && <th className="px-4 py-3" />}
            </tr>
          </thead>
          <tbody>
            {(rules ?? []).map((r) => (
              <tr key={r.id} className="border-b border-border/60">
                <td className="px-4 py-3 font-medium text-ink">{r.name}</td>
                <td className="px-4 py-3 text-muted">
                  {r.scope_type}
                  {r.scope_ref ? ` · ${r.scope_ref}` : ""}
                </td>
                <td className="px-4 py-3 mono text-muted">
                  {r.metric} {r.operator} {r.threshold}
                  {r.for_seconds ? ` for ${r.for_seconds}s` : ""}
                </td>
                <td className="px-4 py-3">
                  <span className="capitalize" style={{ color: SEVERITY_COLOR[r.severity] }}>
                    {r.severity}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <button
                    disabled={!canEdit}
                    onClick={() => toggle(r)}
                    className={`chip ${r.enabled ? "text-nominal" : "text-muted"}`}
                  >
                    {r.enabled ? "enabled" : "disabled"}
                  </button>
                </td>
                {canEdit && (
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <button className="btn-ghost text-xs" onClick={() => setEditing(r)}>
                      {t("edit")}
                    </button>
                    <button className="btn-ghost text-xs text-crit" onClick={() => remove(r)}>
                      {t("delete")}
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {rules && rules.length === 0 && (
              <tr>
                <td colSpan={canEdit ? 6 : 5} className="px-4 py-10 text-center text-sm text-muted">
                  {t("noData")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {(showCreate || editing) && (
        <CreateRuleModal
          rule={editing}
          onClose={() => {
            setShowCreate(false);
            setEditing(null);
          }}
          onSaved={() => {
            setShowCreate(false);
            setEditing(null);
            refetch();
          }}
        />
      )}
    </div>
  );
}

function CreateRuleModal({
  onClose,
  onSaved,
  rule = null,
}: {
  onClose: () => void;
  onSaved: () => void;
  rule?: AlertRule | null;
}) {
  const { t } = usePrefs();
  const [form, setForm] = useState({
    name: rule?.name ?? "",
    scope_type: rule?.scope_type ?? "global",
    scope_ref: rule?.scope_ref ?? "",
    metric: rule?.metric ?? "temp_cpu",
    operator: rule?.operator ?? ">",
    threshold: rule != null ? String(rule.threshold) : "75",
    for_seconds: rule != null ? String(rule.for_seconds) : "60",
    severity: rule?.severity ?? "warning",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body = {
        name: form.name,
        scope_type: form.scope_type,
        scope_ref: form.scope_ref || null,
        metric: form.metric,
        operator: form.operator,
        threshold: Number(form.threshold),
        for_seconds: Number(form.for_seconds),
        severity: form.severity,
      };
      if (rule) await api.updateRule(rule.id, body);
      else await api.createRule(body);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save rule");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" className="panel w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-base font-semibold">{rule ? t("edit") : t("rules")}</h3>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label">{t("name")}</label>
            <input aria-label={t("name")} className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required autoFocus />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">{t("scope")}</label>
              <select aria-label={t("scope")} className="input" value={form.scope_type} onChange={(e) => set("scope_type", e.target.value)}>
                <option value="global">global</option>
                <option value="tag">tag</option>
                <option value="device">device</option>
              </select>
            </div>
            <div>
              <label className="label">Scope ref (tag / device id)</label>
              <input className="input" value={form.scope_ref} onChange={(e) => set("scope_ref", e.target.value)} placeholder="—" />
            </div>
            <div>
              <label className="label">{t("metric")}</label>
              <input aria-label={t("metric")} className="input mono" value={form.metric} onChange={(e) => set("metric", e.target.value)} />
            </div>
            <div>
              <label className="label">Operator</label>
              <select className="input mono" value={form.operator} onChange={(e) => set("operator", e.target.value)}>
                {[">", ">=", "<", "<=", "==", "!="].map((op) => (
                  <option key={op} value={op}>{op}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">{t("threshold")}</label>
              <input aria-label={t("threshold")} className="input mono" type="number" value={form.threshold} onChange={(e) => set("threshold", e.target.value)} required />
            </div>
            <div>
              <label className="label">For (seconds)</label>
              <input className="input mono" type="number" min={0} value={form.for_seconds} onChange={(e) => set("for_seconds", e.target.value)} />
            </div>
            <div>
              <label className="label">{t("severity")}</label>
              <select aria-label={t("severity")} className="input" value={form.severity} onChange={(e) => set("severity", e.target.value)}>
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="critical">critical</option>
              </select>
            </div>
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
