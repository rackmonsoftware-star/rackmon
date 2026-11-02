import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, downloadWithAuth } from "../api";
import LineChart from "../components/LineChart";
import MultiLineChart from "../components/MultiLineChart";
import Sparkline from "../components/Sparkline";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "../auth";
import { usePoll, useWebSocket } from "../hooks";
import { usePrefs } from "../prefs";
import {
  SEVERITY_COLOR,
  escalaDe,
  formatAlertValue,
  thermalColor,
  thermalTextColor,
  timeAgo,
} from "../lib/thermal";
import type { Alert, DeviceStatusKind, MetricCatalog } from "../types";

const STATUS_KIND: Record<number, DeviceStatusKind> = {
  0: "ok",
  1: "warning",
  2: "critical",
  3: "nodata",
};

interface Live {
  value: number;
  status: number;
  unit: string;
  time: string;
}

const METRIC_COLORS = ["#22D3EE", "#34D399", "#FBBF24", "#F87171", "#A78BFA", "#38BDF8"];
const RANGES: Array<{ key: string; label: string; ms: number; agg: string }> = [
  { key: "1h", label: "1h", ms: 3600_000, agg: "raw" },
  { key: "6h", label: "6h", ms: 6 * 3600_000, agg: "1m" },
  { key: "24h", label: "24h", ms: 24 * 3600_000, agg: "5m" },
  { key: "7d", label: "7d", ms: 7 * 24 * 3600_000, agg: "1h" },
];

export default function DeviceDetail() {
  const { id } = useParams();
  const deviceId = Number(id);
  const navigate = useNavigate();
  const { t, theme } = usePrefs();
  const light = theme === "light";
  const { can } = useAuth();

  const { data: device, refetch: refetchDevice } = usePoll(
    () => api.device(deviceId),
    20000,
    [deviceId],
  );
  const { data: alerts, refetch: refetchAlerts } = usePoll(
    () => api.alerts({ device_id: deviceId }),
    8000,
    [deviceId],
  );

  const [live, setLive] = useState<Record<string, Live>>({});
  const [spark, setSpark] = useState<Record<string, number[]>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [extra, setExtra] = useState<Set<string>>(new Set());
  const [showEdit, setShowEdit] = useState(false);
  const [rangeKey, setRangeKey] = useState("6h");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  // Seed live values from the server cache once.
  useEffect(() => {
    api
      .latest()
      .then((all) => {
        const mine = all.filter((v) => v.device_id === deviceId);
        const map: Record<string, Live> = {};
        mine.forEach((v) => {
          map[v.metric] = { value: v.value, status: v.status, unit: v.unit, time: v.time };
        });
        setLive((prev) => ({ ...map, ...prev }));
      })
      .catch(() => undefined);
  }, [deviceId]);

  // Default selected metric = first temperature metric, else first metric.
  useEffect(() => {
    if (!selected && device && device.metrics.length > 0) {
      const temp = device.metrics.find((m) => m.name.startsWith("temp"));
      setSelected((temp ?? device.metrics[0]).name);
    }
  }, [device, selected]);

  const onWsMessage = useCallback((msg: { type: string; [k: string]: unknown }) => {
    if (msg.type === "metric") {
      const metric = msg.metric as string;
      const value = msg.value as number;
      setLive((prev) => ({
        ...prev,
        [metric]: {
          value,
          status: msg.status as number,
          unit: (msg.unit as string) ?? "",
          time: (msg.time as string) ?? new Date().toISOString(),
        },
      }));
      setSpark((prev) => {
        const arr = [...(prev[metric] ?? []), value].slice(-40);
        return { ...prev, [metric]: arr };
      });
    } else if (msg.type === "alert") {
      refetchAlerts();
    }
  }, [refetchAlerts]);

  const wsStatus = useWebSocket(
    Number.isFinite(deviceId) ? [`device.${deviceId}`] : [],
    onWsMessage,
  );

  const isCustom = rangeKey === "custom";
  const range = RANGES.find((r) => r.key === rangeKey) ?? RANGES[1];
  const effAgg = isCustom ? "5m" : range.agg;
  const fromIso = useMemo(
    () => (isCustom && customFrom ? new Date(customFrom).toISOString() : new Date(Date.now() - range.ms).toISOString()),
    [range.ms, isCustom, customFrom],
  );
  const toIso = isCustom && customTo ? new Date(customTo).toISOString() : undefined;

  // Metrics currently plotted: the primary selection + any overlays.
  const activeMetrics = useMemo(
    () => (selected ? [selected, ...Array.from(extra).filter((m) => m !== selected)] : []),
    [selected, extra],
  );

  const { data: multiSeries } = usePoll(
    () =>
      activeMetrics.length
        ? Promise.all(activeMetrics.map((m) => api.series(deviceId, m, effAgg, fromIso, toIso)))
        : Promise.resolve(null),
    20000,
    [deviceId, activeMetrics.join(","), rangeKey, customFrom, customTo],
  );
  const series = multiSeries && multiSeries.length === 1 ? multiSeries[0] : null;

  const { data: anomalyData } = usePoll(
    () => (selected ? api.anomalies(deviceId, selected, fromIso) : Promise.resolve(null)),
    30000,
    [deviceId, selected, rangeKey, fromIso],
  );

  if (!device) {
    return <div className="p-6 text-sm text-muted">{t("loading")}</div>;
  }

  const kind: DeviceStatusKind = device.in_maintenance
    ? "maintenance"
    : selected && live[selected]
      ? STATUS_KIND[live[selected].status] ?? "nodata"
      : "nodata";

  const selectedMetric: MetricCatalog | undefined = device.metrics.find(
    (m) => m.name === selected,
  );

  const wsLabel =
    wsStatus === "connected" ? t("connected") : wsStatus === "connecting" ? t("connecting") : t("disconnected");
  const wsColor = wsStatus === "connected" ? "#34D399" : wsStatus === "connecting" ? "#FBBF24" : "#F87171";

  const toggleMaintenance = async () => {
    if (device.in_maintenance) await api.clearMaintenance(deviceId);
    else await api.setMaintenance(deviceId, 60);
    refetchDevice();
  };

  const removeDevice = async () => {
    if (!window.confirm(`${t("delete")} ${device.name}?`)) return;
    await api.deleteDevice(deviceId);
    navigate("/devices");
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <button onClick={() => navigate("/devices")} className="mb-1 text-xs text-muted hover:text-ink">
            ← {t("devices")}
          </button>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold">{device.name}</h2>
            <StatusBadge status={kind} />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <span className="mono">{device.ip}</span>
            <span>· SNMP v{device.snmp_version}</span>
            {device.vendor && <span>· {device.vendor}</span>}
            {device.rack && <span>· {device.rack}{device.position_u ? ` U${device.position_u}` : ""}</span>}
            {device.tags.map((tag) => (
              <span key={tag} className="chip">{tag}</span>
            ))}
          </div>
        </div>
        {can("operator") && (
          <div className="flex items-center gap-2">
            <button data-testid="edit-device-btn" className="btn-ghost" onClick={() => setShowEdit(true)}>
              {t("edit")}
            </button>
            <button className="btn-ghost" onClick={toggleMaintenance}>
              {device.in_maintenance ? t("exitMaintenance") : t("enterMaintenance")}
            </button>
            <button className="btn-danger" onClick={removeDevice}>
              {t("delete")}
            </button>
          </div>
        )}
      </div>

      {/* Live metric cards */}
      <div>
        <div className="mb-2 flex items-center gap-2 text-xs">
          <span className="h-2 w-2 rounded-full" style={{ background: wsColor, animation: wsStatus === "connected" ? "pulse2 1.6s ease-in-out infinite" : undefined }} />
          <span style={{ color: wsColor }}>{wsLabel}</span>
        </div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
          {device.metrics.map((m) => {
            const v = live[m.name];
            const isTemp = m.name.startsWith("temp");
            // Cada metrica con SU escala: temp_inlet avisa a 27 y temp_cpu a 70.
            const esc = escalaDe(m.name);
            const color = isTemp ? thermalColor(v?.value, esc) : "#22D3EE";
            const valueColor = isTemp ? thermalTextColor(v?.value, light, esc) : light ? "#0E7490" : "#22D3EE";
            const inOverlay = extra.has(m.name) && m.name !== selected;
            return (
              <div
                key={m.id}
                className={`panel relative p-4 text-left transition-colors hover:border-accent/40 ${selected === m.name ? "border-accent/50" : inOverlay ? "border-nominal/40" : ""}`}
              >
                {selected && m.name !== selected && (
                  <button
                    data-testid="overlay-toggle"
                    title={t("addMetric")}
                    onClick={() =>
                      setExtra((s) => {
                        const n = new Set(s);
                        if (n.has(m.name)) n.delete(m.name);
                        else n.add(m.name);
                        return n;
                      })
                    }
                    className={`absolute right-2 top-2 h-5 w-5 rounded text-xs ${inOverlay ? "bg-nominal/20 text-nominal" : "text-muted hover:text-ink"}`}
                  >
                    {inOverlay ? "−" : "+"}
                  </button>
                )}
                <button className="w-full text-left" onClick={() => setSelected(m.name)}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs uppercase tracking-wide text-muted">{m.name}</span>
                    <Sparkline values={spark[m.name] ?? []} color={color} width={64} height={20} />
                  </div>
                  <div className="mono mt-1 text-xl" style={{ color: valueColor }}>
                    {v ? `${v.value.toFixed(1)}${v.unit || m.unit}` : "—"}
                  </div>
                  <div className="text-[10px] text-muted">{v ? timeAgo(v.time) : t("noData")}</div>
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Historical chart */}
      <div className="panel p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">{t("history")}</h3>
            {selectedMetric && <span className="chip">{selectedMetric.name} · {selectedMetric.unit}</span>}
            {anomalyData && anomalyData.count > 0 && (
              <span className="chip text-crit" title={t("anomalies")}>
                {anomalyData.count} {t("anomalies")}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border border-border p-0.5">
              {RANGES.map((r) => (
                <button
                  key={r.key}
                  onClick={() => setRangeKey(r.key)}
                  className={`rounded px-2.5 py-1 text-xs transition-colors ${rangeKey === r.key ? "bg-surface2 text-ink" : "text-muted hover:text-ink"}`}
                >
                  {r.label}
                </button>
              ))}
              <button
                data-testid="range-custom"
                onClick={() => setRangeKey("custom")}
                className={`rounded px-2.5 py-1 text-xs transition-colors ${isCustom ? "bg-surface2 text-ink" : "text-muted hover:text-ink"}`}
              >
                {t("customRange")}
              </button>
            </div>
            {isCustom && (
              <div className="flex items-center gap-1" data-testid="custom-range-inputs">
                <input
                  type="datetime-local"
                  className="input py-1 text-xs"
                  value={customFrom}
                  onChange={(e) => setCustomFrom(e.target.value)}
                />
                <span className="text-xs text-muted">→</span>
                <input
                  type="datetime-local"
                  className="input py-1 text-xs"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                />
              </div>
            )}
            {selected && (
              <a
                className="btn-ghost text-xs"
                href={api.exportUrl(deviceId, selected, "csv")}
                onClick={(e) => {
                  // Auth + res.ok + 401-refresh are handled by downloadWithAuth,
                  // so an expired token or a 5xx never saves an error body as .csv.
                  e.preventDefault();
                  void downloadWithAuth(api.exportUrl(deviceId, selected, "csv"), `${selected}_${deviceId}.csv`);
                }}
              >
                {t("export")}
              </a>
            )}
          </div>
        </div>
        {multiSeries && multiSeries.length > 1 ? (
          <MultiLineChart
            series={multiSeries.map((s, i) => ({
              name: activeMetrics[i],
              color: METRIC_COLORS[i % METRIC_COLORS.length],
              samples: s.samples,
            }))}
          />
        ) : series ? (
          <LineChart
            samples={series.samples}
            unit={series.unit}
            thermal={selected?.startsWith("temp") ?? false}
            escala={escalaDe(selected)}
            warn={selectedMetric?.warn_threshold ?? null}
            crit={selectedMetric?.crit_threshold ?? null}
          />
        ) : (
          <div className="flex h-60 items-center justify-center text-sm text-muted">{t("loading")}</div>
        )}
        {anomalyData && (
          <div className="mt-4 border-t border-border pt-3">
            {anomalyData.count > 0 ? (
              <>
                <div className="mb-2 text-xs font-medium text-crit">
                  {anomalyData.count} {t("anomaliesDetected")}
                </div>
                <div className="flex flex-wrap gap-2">
                  {anomalyData.anomalies.slice(0, 12).map((a, i) => (
                    <span key={i} className="chip mono" style={{ color: "#F87171" }}>
                      {a.value.toFixed(1)}
                      {anomalyData.unit} · z={a.z} · {timeAgo(a.time)}
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <div className="text-xs text-muted">{t("noAnomalies")}</div>
            )}
          </div>
        )}
      </div>

      {/* Timeline notes */}
      <NotesPanel deviceId={deviceId} metric={selected} canAct={can("operator")} />

      {/* Device alerts */}
      <div className="panel p-5">
        <h3 className="mb-4 text-sm font-semibold">{t("alerts")}</h3>
        <div className="space-y-2">
          {alerts && alerts.length > 0 ? (
            alerts.map((a) => (
              <AlertRow key={a.id} alert={a} onChanged={refetchAlerts} canAct={can("operator")} />
            ))
          ) : (
            <div className="text-sm text-muted">{t("noAlerts")}</div>
          )}
        </div>
      </div>

      {showEdit && (
        <EditDeviceModal
          device={device}
          onClose={() => setShowEdit(false)}
          onSaved={() => {
            setShowEdit(false);
            refetchDevice();
          }}
        />
      )}
    </div>
  );
}

function AlertRow({
  alert,
  onChanged,
  canAct,
}: {
  alert: Alert;
  onChanged: () => void;
  canAct: boolean;
}) {
  const { t } = usePrefs();
  const [busy, setBusy] = useState(false);

  const act = async (kind: "ack" | "resolve") => {
    const comment = window.prompt(`${kind === "ack" ? t("acknowledge") : t("resolve")} — ${t("comment")}:`);
    if (!comment) return;
    setBusy(true);
    try {
      if (kind === "ack") await api.ackAlert(alert.id, comment);
      else await api.resolveAlert(alert.id, comment);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-3 rounded-md border border-border px-3 py-2">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: SEVERITY_COLOR[alert.severity] }} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-ink">{alert.message}</div>
        <div className="text-xs text-muted">
          {timeAgo(alert.started_at)} · {alert.value != null ? formatAlertValue(alert.metric, alert.value) : ""}
        </div>
      </div>
      <span className="chip capitalize" style={{ color: SEVERITY_COLOR[alert.severity] }}>
        {alert.state}
      </span>
      {canAct && alert.state !== "resolved" && (
        <div className="flex gap-1">
          {alert.state === "firing" && (
            <button className="btn-ghost text-xs" disabled={busy} onClick={() => act("ack")}>
              {t("acknowledge")}
            </button>
          )}
          <button className="btn-ghost text-xs" disabled={busy} onClick={() => act("resolve")}>
            {t("resolve")}
          </button>
        </div>
      )}
    </div>
  );
}

function NotesPanel({
  deviceId,
  metric,
  canAct,
}: {
  deviceId: number;
  metric: string | null;
  canAct: boolean;
}) {
  const { t } = usePrefs();
  const { data, refetch } = usePoll(() => api.annotations(deviceId), 30000, [deviceId]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  const saveEdit = async (id: number) => {
    if (!editText.trim()) return;
    await api.updateAnnotation(id, editText.trim());
    setEditingId(null);
    refetch();
  };

  const add = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api.createAnnotation({ device_id: deviceId, metric: metric || null, text: text.trim() });
      setText("");
      refetch();
    } finally {
      setBusy(false);
    }
  };
  const del = async (id: number) => {
    await api.deleteAnnotation(id);
    refetch();
  };

  return (
    <div className="panel p-5">
      <h3 className="mb-3 text-sm font-semibold">{t("notes")}</h3>
      {canAct && (
        <div className="mb-3 flex gap-2">
          <input
            className="input flex-1"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder={metric ? `${t("addNote")} (${metric})` : t("addNote")}
          />
          <button className="btn-primary" onClick={add} disabled={busy}>
            {t("addNote")}
          </button>
        </div>
      )}
      <div className="space-y-2">
        {data && data.length > 0 ? (
          data.map((a) => (
            <div key={a.id} className="flex items-start gap-3 rounded-md border border-border px-3 py-2">
              <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-accent" />
              <div className="min-w-0 flex-1">
                {editingId === a.id ? (
                  <div className="flex gap-2">
                    <input
                      className="input flex-1"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && saveEdit(a.id)}
                      autoFocus
                    />
                    <button className="btn-primary" onClick={() => saveEdit(a.id)}>
                      {t("save")}
                    </button>
                    <button className="btn-ghost" onClick={() => setEditingId(null)}>
                      {t("cancel")}
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="text-sm text-ink">{a.text}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                      <span>{timeAgo(a.at)}</span>
                      {a.metric && <span className="chip">{a.metric}</span>}
                    </div>
                  </>
                )}
              </div>
              {canAct && editingId !== a.id && (
                <div className="flex gap-1">
                  <button
                    data-testid="edit-note-btn"
                    className="btn-ghost text-xs"
                    onClick={() => {
                      setEditingId(a.id);
                      setEditText(a.text);
                    }}
                  >
                    {t("edit")}
                  </button>
                  <button className="btn-ghost text-xs text-crit" aria-label={t("delete")} onClick={() => del(a.id)}>
                    ✕
                  </button>
                </div>
              )}
            </div>
          ))
        ) : (
          <div className="text-sm text-muted">{t("noData")}</div>
        )}
      </div>
    </div>
  );
}

function EditDeviceModal({
  device,
  onClose,
  onSaved,
}: {
  device: {
    id: number;
    name: string;
    ip: string;
    snmp_version: string;
    vendor?: string | null;
    rack?: string | null;
    position_u?: number | null;
    tags: string[];
  };
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = usePrefs();
  const [form, setForm] = useState({
    name: device.name ?? "",
    ip: device.ip ?? "",
    snmp_version: device.snmp_version ?? "2c",
    snmp_community: "",
    vendor: device.vendor ?? "",
    rack: device.rack ?? "",
    position_u: device.position_u != null ? String(device.position_u) : "",
    tags: (device.tags ?? []).join(", "),
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        name: form.name,
        ip: form.ip,
        snmp_version: form.snmp_version,
        vendor: form.vendor || null,
        rack: form.rack || null,
        position_u: form.position_u ? Number(form.position_u) : null,
        tags: form.tags ? form.tags.split(",").map((s) => s.trim()).filter(Boolean) : [],
      };
      if (form.snmp_community) body.snmp_community = form.snmp_community;
      await api.updateDevice(device.id, body);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update device");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" className="panel w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-base font-semibold">{t("edit")} — {device.name}</h3>
        <form onSubmit={submit} className="space-y-4" data-testid="edit-device-form">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="label">{t("name")}</label>
              <input aria-label={t("name")} className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required autoFocus />
            </div>
            <div>
              <label className="label">{t("ip")}</label>
              <input aria-label={t("ip")} className="input mono" value={form.ip} onChange={(e) => set("ip", e.target.value)} required />
            </div>
            <div>
              <label className="label">{t("version")}</label>
              <select aria-label={t("version")} className="input" value={form.snmp_version} onChange={(e) => set("snmp_version", e.target.value)}>
                <option value="2c">v2c</option>
                <option value="1">v1</option>
                <option value="3">v3</option>
              </select>
            </div>
            <div>
              <label className="label">{t("community")}</label>
              <input aria-label={t("community")} className="input mono" value={form.snmp_community} onChange={(e) => set("snmp_community", e.target.value)} placeholder="•••••• (unchanged)" />
            </div>
            <div>
              <label className="label">{t("vendor")}</label>
              <input aria-label={t("vendor")} className="input" value={form.vendor} onChange={(e) => set("vendor", e.target.value)} />
            </div>
            <div>
              <label className="label">{t("rack")}</label>
              <input aria-label={t("rack")} className="input" value={form.rack} onChange={(e) => set("rack", e.target.value)} placeholder="RACK-A" />
            </div>
            <div>
              <label className="label">{t("position")}</label>
              <input aria-label={t("position")} className="input mono" type="number" min={1} max={60} value={form.position_u} onChange={(e) => set("position_u", e.target.value)} />
            </div>
            <div className="col-span-2">
              <label className="label">{t("tags")}</label>
              <input aria-label={t("tags")} className="input" value={form.tags} onChange={(e) => set("tags", e.target.value)} placeholder="compute, prod" />
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
              {busy ? "…" : t("save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
