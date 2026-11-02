import { useNavigate } from "react-router-dom";

import { api } from "../api";
import AvisoInstalacionMuda from "../components/AvisoInstalacionMuda";
import RackElevation from "../components/RackElevation";
import StatusBadge from "../components/StatusBadge";
import { usePoll } from "../hooks";
import { usePrefs } from "../prefs";
import {
  SEVERITY_COLOR,
  STATUS_COLOR,
  STATUS_I18N_KEY,
  UMBRALES,
  escalaDe,
  formatTemp,
  formatTempC,
  gradienteCss,
  posicionEnLeyenda,
  thermalColor,
  thermalTextColor,
  timeAgo,
} from "../lib/thermal";
import type { DeviceStatusKind } from "../types";

function StatCard({
  label,
  value,
  accent,
  sub,
}: {
  label: string;
  value: string;
  accent?: string;
  sub?: string;
}) {
  return (
    <div className="panel p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mono mt-1 text-2xl" style={{ color: accent ?? "var(--ink)" }}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

const STATUS_ORDER: DeviceStatusKind[] = ["ok", "warning", "critical", "maintenance", "nodata"];

export default function Overview() {
  const { t, theme } = usePrefs();
  const light = theme === "light";
  const navigate = useNavigate();
  const { data: overview, error: overviewError } = usePoll(api.overview, 5000);
  const { data: statuses } = usePoll(api.statuses, 5000);
  const { data: alerts } = usePoll(() => api.alerts({ active: true }), 5000);

  const counts = overview?.status_counts;
  const total = overview?.devices_total ?? 0;
  // Mientras carga NO se enseñan ceros. Un panel de monitorización que dice
  // "0 alertas activas" en verde durante el primer segundo está afirmando algo
  // falso y tranquilizador justo en lo que la gente mira primero — y encima el
  // panel de abajo ya estaba listando alertas disparadas al mismo tiempo.
  const cargando = !overview;
  const SIN_DATO = "—";

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">{t("overview")}</h2>
      </div>

      {/* Lo primero de todo: si esta instalación no puede avisar de nada, eso
          importa más que cualquier número de la pantalla. */}
      <AvisoInstalacionMuda
        reglas={overview?.alert_rules_active}
        canales={overview?.notification_channels}
        demo={overview?.demo_mode}
      />

      {overviewError && (
        <div
          className="rounded-md px-4 py-2 text-sm text-ink"
          role="status"
          style={{ border: "1px solid #FBBF2466", background: "#FBBF2414" }}
        >
          Connection lost — showing the last known data.
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label={t("devicesTotal")} value={cargando ? SIN_DATO : String(total)} />
        <StatCard
          label={t("activeAlerts")}
          value={cargando ? SIN_DATO : String(overview?.firing_alerts ?? 0)}
          accent={
            cargando
              ? undefined
              : overview?.firing_alerts
                ? STATUS_COLOR.critical
                : STATUS_COLOR.ok
          }
        />
        <StatCard
          label={t("avgTemp")}
          value={formatTempC(overview?.avg_temperature)}
          accent={thermalTextColor(overview?.avg_temperature ?? undefined, light)}
        />
        <StatCard
          label={t("maxTemp")}
          value={formatTempC(overview?.max_temperature)}
          accent={thermalTextColor(overview?.max_temperature ?? undefined, light)}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Rack heatmap — signature view */}
        <div className="panel p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold">{t("rackHeatmap")}</h3>
            <ThermalLegend />
          </div>
          {statuses ? (
            <RackElevation statuses={statuses} />
          ) : (
            <div className="p-6 text-sm text-muted">{t("loading")}</div>
          )}
        </div>

        {/* Fleet status */}
        <div className="panel p-5">
          <h3 className="mb-4 text-sm font-semibold">{t("statusBreakdown")}</h3>
          <div className="space-y-3">
            {STATUS_ORDER.map((k) => {
              const n = counts?.[k] ?? 0;
              const pct = total ? (n / total) * 100 : 0;
              return (
                <div key={k}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-muted">{t(STATUS_I18N_KEY[k])}</span>
                    <span className="mono text-ink">{cargando ? SIN_DATO : n}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full border border-border bg-surface2">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${pct}%`, background: STATUS_COLOR[k] }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Hottest devices */}
        <div className="panel p-5">
          <h3 className="mb-4 text-sm font-semibold">{t("hottest")}</h3>
          <div className="space-y-2">
            {overview?.hottest.length ? (
              overview.hottest.map((d) => {
                const maxT = overview.max_temperature ?? d.temperature ?? 1;
                const pct = d.temperature ? Math.min(100, (d.temperature / maxT) * 100) : 0;
                return (
                  <button
                    key={d.device.id}
                    onClick={() => navigate(`/devices/${d.device.id}`)}
                    className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left hover:bg-surface2"
                  >
                    <div className="w-32 truncate text-sm text-ink">{d.device.name}</div>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface2">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${pct}%`,
                          background: thermalColor(d.temperature, escalaDe(d.temperature_metric)),
                        }}
                      />
                    </div>
                    <div
                      className="mono w-14 text-right text-sm"
                      style={{ color: thermalTextColor(d.temperature, light, escalaDe(d.temperature_metric)) }}
                    >
                      {formatTemp(d.temperature)}
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="text-sm text-muted">{t("noData")}</div>
            )}
          </div>
        </div>

        {/* Active alerts */}
        <div className="panel p-5">
          <h3 className="mb-4 text-sm font-semibold">{t("activeAlerts")}</h3>
          <div className="space-y-2">
            {alerts && alerts.length > 0 ? (
              alerts.slice(0, 8).map((a) => (
                <button
                  key={a.id}
                  onClick={() => navigate(`/devices/${a.device_id}`)}
                  className="flex w-full items-center gap-3 rounded-md border border-border px-3 py-2 text-left hover:border-accent/40"
                >
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ background: SEVERITY_COLOR[a.severity] }}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-ink">{a.message}</div>
                    <div className="text-xs text-muted">{timeAgo(a.started_at)}</div>
                  </div>
                  <span className="chip capitalize" style={{ color: SEVERITY_COLOR[a.severity] }}>
                    {a.state}
                  </span>
                </button>
              ))
            ) : (
              <div className="flex items-center gap-2 text-sm text-nominal">
                <StatusBadge status="ok" />
                {t("noAlerts")}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** La leyenda del mapa. Sale del mismo sitio que los colores del mapa, y marca
    dónde están los dos umbrales de verdad, para que el color se pueda leer:
    ámbar = aviso, rojo = crítico. Antes decía "15° … 90°" con unos colores
    escritos a mano que ya no correspondían a nada. */
function ThermalLegend() {
  const { t } = usePrefs();
  const { frio, aviso, critico, tope } = UMBRALES.entrada;
  return (
    <div className="flex items-center gap-2 text-[10px] text-muted">
      <span className="mono">{frio}°</span>
      <div
        className="relative h-2 w-32 rounded-full"
        style={{ background: gradienteCss("entrada") }}
        title={`${t("statusWarning")} ${aviso}°C · ${t("statusCritical")} ${critico}°C`}
      >
        {[aviso, critico].map((u) => (
          <span
            key={u}
            className="absolute top-[-3px] h-[14px] w-px bg-ink/70"
            style={{ left: `${posicionEnLeyenda(u, "entrada")}%` }}
          />
        ))}
      </div>
      <span className="mono">{tope}°</span>
      <span className="hidden sm:inline">
        {aviso}° {t("statusWarning").toLowerCase()} · {critico}° {t("statusCritical").toLowerCase()}
      </span>
    </div>
  );
}
