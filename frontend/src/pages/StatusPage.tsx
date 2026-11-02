import { useEffect, useState } from "react";

import { api, type PublicStatus } from "../api";
import StatusBadge from "../components/StatusBadge";
import { formatTemp } from "../lib/thermal";
import type { DeviceStatusKind } from "../types";

const OVERALL: Record<string, { text: string; dot: string }> = {
  ok: { text: "All systems operational", dot: "bg-nominal" },
  warning: { text: "Degraded — warnings active", dot: "bg-warn" },
  critical: { text: "Major issues detected", dot: "bg-crit" },
  nodata: { text: "No data reported", dot: "bg-muted" },
};

export default function StatusPage() {
  const [data, setData] = useState<PublicStatus | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .publicStatus()
        .then((d) => {
          if (alive) {
            setData(d);
            setError(false); // recover if a previous poll had failed
          }
        })
        .catch(() => alive && setError(true));
    load();
    const id = window.setInterval(load, 30000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4 text-center text-sm text-muted">
        This status page is not available.
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted">Loading…</div>
    );
  }

  const overall = OVERALL[data.overall] ?? { text: data.overall, dot: "bg-muted" };

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-3xl px-4 py-10">
        <div className="mb-6 flex items-center gap-3">
          <span className={`h-3 w-3 rounded-full ${overall.dot}`} />
          <h1 className="text-xl font-semibold text-ink">{data.title}</h1>
        </div>

        <div className="panel mb-5 flex flex-wrap items-center justify-between gap-2 p-4">
          <span className="text-sm font-medium text-ink">{overall.text}</span>
          <span className="text-xs text-muted">
            Updated {new Date(data.generated_at).toLocaleString()}
          </span>
        </div>

        <div className="mb-5 flex flex-wrap gap-2 text-xs">
          {Object.entries(data.summary)
            .filter(([, n]) => n > 0)
            .map(([k, n]) => (
              <span key={k} className="chip">
                {n} {k}
              </span>
            ))}
        </div>

        <div className="panel divide-y divide-border/60 overflow-hidden">
          {data.devices.map((d) => (
            <div key={d.name} className="flex items-center justify-between px-4 py-3">
              <span className="truncate text-sm text-ink">{d.name}</span>
              <div className="flex shrink-0 items-center gap-3">
                {d.temperature != null && (
                  <span className="mono text-xs text-muted">{formatTemp(d.temperature)}</span>
                )}
                <StatusBadge status={d.status as DeviceStatusKind} />
              </div>
            </div>
          ))}
          {data.devices.length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-muted">No devices.</div>
          )}
        </div>

        <div className="mt-8 text-center text-[11px] text-muted">Powered by RackMon</div>
      </div>
    </div>
  );
}
