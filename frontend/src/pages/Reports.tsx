import { useEffect, useMemo, useState } from "react";

import { api, downloadWithAuth } from "../api";
import { usePrefs } from "../prefs";
import { SEVERITY_COLOR, thermalTextColor } from "../lib/thermal";

function toLocalInput(d: Date): string {
  // yyyy-MM-ddThh:mm for <input type="datetime-local">
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function Reports() {
  const { t, theme } = usePrefs();
  const light = theme === "light";
  const now = useMemo(() => new Date(), []);
  const weekAgo = useMemo(() => new Date(Date.now() - 7 * 864e5), []);
  const [from, setFrom] = useState(toLocalInput(weekAgo));
  const [to, setTo] = useState(toLocalInput(now));
  const [data, setData] = useState<Awaited<ReturnType<typeof api.reportAdhoc>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [slaTarget, setSlaTarget] = useState("99.9");
  const [sla, setSla] = useState<Awaited<ReturnType<typeof api.reportSla>> | null>(null);

  useEffect(() => {
  }, []);

  const fromIso = () => new Date(from).toISOString();
  const toIso = () => new Date(to).toISOString();

  const load = async () => {
    setBusy(true);
    try {
      setData(await api.reportAdhoc(fromIso(), toIso()));
    } finally {
      setBusy(false);
    }
  };

  const downloadPdf = () =>
    downloadWithAuth(api.reportPdfUrl(fromIso(), toIso()), "rackmon_report.pdf");
  const downloadCsv = () =>
    downloadWithAuth(api.reportCsvUrl(fromIso(), toIso()), "rackmon_report.csv");

  const loadSla = async () => {
    setBusy(true);
    try {
      setSla(await api.reportSla(fromIso(), toIso(), Number(String(slaTarget).replace(",", ".")) || 99.9));
    } finally {
      setBusy(false);
    }
  };
  const downloadSlaPdf = () =>
    downloadWithAuth(api.slaPdfUrl(fromIso(), toIso(), Number(String(slaTarget).replace(",", ".")) || 99.9), "rackmon_sla.pdf");

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">{t("reports")}</h2>

      <div className="panel flex flex-wrap items-end gap-4 p-4">
        <div>
          <label className="label">{t("fromLabel")}</label>
          <input aria-label={t("fromLabel")} type="datetime-local" className="input" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div>
          <label className="label">{t("toLabel")}</label>
          <input aria-label={t("toLabel")} type="datetime-local" className="input" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <button className="btn-secondary" onClick={load} disabled={busy}>
          {busy ? "…" : t("summary")}
        </button>
        <button className="btn-primary" onClick={downloadPdf}>
          {t("downloadPdf")}
        </button>
        <button data-testid="report-csv-btn" className="btn-secondary" onClick={downloadCsv}>
          CSV
        </button>
      </div>

      {data && (
        <>
          <div className="panel p-5">
            <h3 className="mb-3 text-sm font-semibold">{t("activeAlerts")}</h3>
            <div className="flex gap-6 text-sm">
              {(["critical", "warning", "info"] as const).map((s) => (
                <div key={s} className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: SEVERITY_COLOR[s] }} />
                  <span className="capitalize text-muted">{s}</span>
                  <span className="mono text-ink">{data.alerts_by_severity[s] ?? 0}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-4 py-3 font-medium">{t("name")}</th>
                  <th className="px-4 py-3 text-right font-medium">Avg</th>
                  <th className="px-4 py-3 text-right font-medium">Max</th>
                  <th className="px-4 py-3 text-right font-medium">{t("overWarn")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("overCrit")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("availability")}</th>
                </tr>
              </thead>
              <tbody>
                {data.per_device.map((d) => (
                  <tr key={d.device_id} className="border-b border-border/60">
                    <td className="px-4 py-2.5 text-ink">{d.name}</td>
                    <td
                      className="px-4 py-2.5 text-right mono"
                      style={{ color: thermalTextColor(d.avg_temp, light, d.sensor === "componente" ? "componente" : "entrada") }}
                    >
                      {d.avg_temp ?? "—"}
                    </td>
                    <td
                      className="px-4 py-2.5 text-right mono"
                      style={{ color: thermalTextColor(d.max_temp, light, d.sensor === "componente" ? "componente" : "entrada") }}
                    >
                      {d.max_temp ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right mono text-muted">{d.pct_over_warn}%</td>
                    <td className="px-4 py-2.5 text-right mono text-muted">{d.pct_over_crit}%</td>
                    <td className="px-4 py-2.5 text-right mono text-muted">{d.availability_pct}%</td>
                  </tr>
                ))}
                {data.per_device.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-sm text-muted">
                      {t("noData")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="panel space-y-3 p-5">
        <h3 className="text-sm font-semibold">{t("slaReport")}</h3>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="label">{t("slaTarget")}</label>
            <input aria-label={t("slaTarget")} className="input mono w-28" type="text" inputMode="decimal" pattern="[0-9.]*"
                   value={slaTarget} onChange={(e) => setSlaTarget(e.target.value)} />
          </div>
          <button className="btn-secondary" onClick={loadSla} disabled={busy}>{busy ? "…" : t("summary")}</button>
          <button className="btn-primary" onClick={downloadSlaPdf}>{t("downloadPdf")}</button>
        </div>
        {sla && (
          <>
            <div className="text-sm text-muted">
              {t("overallAvailability")}: <span className="mono text-ink">{sla.overall_availability_pct}%</span>
              {" · "}{sla.devices_meeting_sla}/{sla.device_count} ≥ {sla.target_pct}%
              {" · "}{sla.total_incidents} {t("incidentsCount")}
            </div>
            <div className="panel-2 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
                    <th className="px-4 py-2 font-medium">{t("name")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("availability")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("downtime")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("incidentsCount")}</th>
                    <th className="px-4 py-2 text-right font-medium">{t("mttr")}</th>
                    <th className="px-4 py-2 text-right font-medium">SLA</th>
                  </tr>
                </thead>
                <tbody>
                  {sla.per_device.map((d) => (
                    <tr key={d.device_id} className="border-b border-border/60">
                      <td className="px-4 py-2 text-ink">{d.name}</td>
                      <td className="px-4 py-2 text-right mono">{d.availability_pct}%</td>
                      <td className="px-4 py-2 text-right mono text-muted">{d.downtime_minutes}</td>
                      <td className="px-4 py-2 text-right mono text-muted">{d.incidents}</td>
                      <td className="px-4 py-2 text-right mono text-muted">{d.mttr_minutes ?? "—"}</td>
                      <td className="px-4 py-2 text-right">
                        <span className={d.sla_met ? "text-nominal" : "text-crit"}>{d.sla_met ? "OK" : "MISS"}</span>
                      </td>
                    </tr>
                  ))}
                  {sla.per_device.length === 0 && (
                    <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-muted">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
