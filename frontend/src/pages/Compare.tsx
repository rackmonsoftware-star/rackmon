import { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import MultiLineChart, { type CompareSeries } from "../components/MultiLineChart";
import { usePoll } from "../hooks";
import { usePrefs } from "../prefs";

const PALETTE = ["#22D3EE", "#34D399", "#FBBF24", "#F87171", "#38BDF8", "#a78bfa", "#f472b6", "#facc15"];
const METRICS = ["temp_cpu", "temp_inlet", "cpu_load", "mem_used", "fan_rpm"];
const RANGES: Array<{ key: string; label: string; ms: number; agg: string }> = [
  { key: "1h", label: "1h", ms: 3600_000, agg: "raw" },
  { key: "6h", label: "6h", ms: 6 * 3600_000, agg: "1m" },
  { key: "24h", label: "24h", ms: 24 * 3600_000, agg: "5m" },
];

export default function Compare() {
  const { t } = usePrefs();
  const { data: devices } = usePoll(() => api.devices(), 30000);
  const [metric, setMetric] = useState("temp_cpu");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [rangeKey, setRangeKey] = useState("6h");
  const [series, setSeries] = useState<CompareSeries[]>([]);
  const [loading, setLoading] = useState(false);

  const range = RANGES.find((r) => r.key === rangeKey)!;
  const fromIso = useMemo(() => new Date(Date.now() - range.ms).toISOString(), [range.ms]);

  useEffect(() => {
    const ids = [...selected];
    if (ids.length === 0) {
      setSeries([]);
      setLoading(false); // clear a spinner left on from an in-flight fetch
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all(
      ids.map((id) =>
        api.series(id, metric, range.agg, fromIso).catch(() => null)),
    ).then((results) => {
      if (cancelled) return;
      const nameById = new Map((devices ?? []).map((d) => [d.id, d.name]));
      const built: CompareSeries[] = [];
      results.forEach((res, i) => {
        if (res && res.samples.length) {
          built.push({
            name: nameById.get(ids[i]) ?? `#${ids[i]}`,
            color: PALETTE[i % PALETTE.length],
            samples: res.samples,
          });
        }
      });
      setSeries(built);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [[...selected].join(","), metric, rangeKey, fromIso]);

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">{t("compare")}</h2>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-4">
        {/* Controls */}
        <div className="panel p-4 lg:col-span-1">
          <label className="label">{t("metric")}</label>
          <select aria-label={t("metric")} className="input mb-4" value={metric} onChange={(e) => setMetric(e.target.value)}>
            {METRICS.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>

          <label className="label">{t("range")}</label>
          <div className="mb-4 flex rounded-md border border-border p-0.5">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => setRangeKey(r.key)}
                className={`flex-1 rounded px-2 py-1 text-xs ${rangeKey === r.key ? "bg-surface2 text-ink" : "text-muted hover:text-ink"}`}
              >
                {r.label}
              </button>
            ))}
          </div>

          <label className="label">{t("devices")}</label>
          <div className="max-h-72 space-y-1 overflow-auto">
            {(devices ?? []).map((d) => (
              <label key={d.id} className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-surface2">
                <input type="checkbox" checked={selected.has(d.id)} onChange={() => toggle(d.id)} />
                <span className="truncate text-ink">{d.name}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Chart */}
        <div className="panel p-5 lg:col-span-3">
          {loading ? (
            <div className="flex h-72 items-center justify-center text-sm text-muted">{t("loading")}</div>
          ) : (
            <MultiLineChart series={series} unit={metric.startsWith("temp") ? "°C" : ""} emptyLabel={t("selectDevicesToCompare")} />
          )}
        </div>
      </div>
    </div>
  );
}
