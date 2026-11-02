import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { DeviceStatus } from "../types";
import { STATUS_COLOR, escalaDe, formatTemp, thermalColor } from "../lib/thermal";

interface Props {
  statuses: DeviceStatus[];
}

const U_HEIGHT = 12; // px per rack unit
const MIN_U = 12;

interface Slot {
  status: DeviceStatus;
  start: number;
  size: number;
}

/**
 * Renders each rack as a vertical elevation, colouring occupied units by
 * temperature along the thermal ramp. This is RackMon's signature view: a
 * glance tells you where the heat is. Unplaced devices are grouped separately.
 */
export default function RackElevation({ statuses }: Props) {
  const navigate = useNavigate();
  const [hover, setHover] = useState<{ s: DeviceStatus; x: number; y: number } | null>(null);

  const { racks, unplaced } = useMemo(() => {
    const byRack = new Map<string, Slot[]>();
    const noRack: DeviceStatus[] = [];
    for (const s of statuses) {
      if (s.device.rack && s.device.position_u != null) {
        const slots = byRack.get(s.device.rack) ?? [];
        slots.push({ status: s, start: s.device.position_u, size: s.device.size_u || 1 });
        byRack.set(s.device.rack, slots);
      } else {
        noRack.push(s);
      }
    }
    const racks = [...byRack.entries()]
      .map(([name, slots]) => {
        const maxU = Math.max(MIN_U, ...slots.map((sl) => sl.start + sl.size - 1));
        return { name, slots, maxU };
      })
      .sort((a, b) => a.name.localeCompare(b.name));
    return { racks, unplaced: noRack };
  }, [statuses]);

  if (statuses.length === 0) {
    return <div className="p-6 text-sm text-muted">No devices to display.</div>;
  }

  return (
    <div className="relative">
      <div className="flex flex-wrap gap-6">
        {racks.map((rack) => (
          <div key={rack.name} className="flex flex-col items-center">
            <div className="mb-2 text-xs font-medium text-muted">{rack.name}</div>
            <div className="flex items-stretch gap-1">
              {/* U scale */}
              <div className="flex flex-col justify-between py-0.5 text-[9px] text-muted mono">
                <span>{rack.maxU}U</span>
                <span>1U</span>
              </div>
              <div
                className="relative w-24 rounded border border-border bg-surface2"
                style={{ height: rack.maxU * U_HEIGHT }}
              >
                {/* Empty unit gridlines */}
                {Array.from({ length: rack.maxU }, (_, i) => (
                  <div
                    key={i}
                    className="absolute left-0 right-0 border-b border-border/40"
                    style={{ top: i * U_HEIGHT, height: U_HEIGHT }}
                  />
                ))}
                {/* Devices */}
                {rack.slots.map((slot) => {
                  const topU = rack.maxU - (slot.start + slot.size - 1);
                  const temp = slot.status.temperature;
                  const color =
                    slot.status.status === "nodata" || temp == null
                      ? STATUS_COLOR.nodata
                      : thermalColor(temp, escalaDe(slot.status.temperature_metric));
                  return (
                    <button
                      key={slot.status.device.id}
                      aria-label={`${slot.status.device.name}${temp == null ? "" : ` — ${formatTemp(temp)}`}`}
                      title={slot.status.device.name}
                      className="absolute left-0.5 right-0.5 flex items-center justify-center rounded-sm text-[9px] font-medium transition-transform hover:z-10 hover:scale-[1.04]"
                      style={{
                        top: topU * U_HEIGHT + 1,
                        height: slot.size * U_HEIGHT - 2,
                        background: color,
                        color: "#0b0f14",
                        boxShadow:
                          slot.status.status === "critical"
                            ? "0 0 0 1px #F87171, 0 0 10px -2px #F87171"
                            : undefined,
                      }}
                      onClick={() => navigate(`/devices/${slot.status.device.id}`)}
                      onMouseEnter={(e) =>
                        setHover({
                          s: slot.status,
                          x: e.currentTarget.getBoundingClientRect().right,
                          y: e.currentTarget.getBoundingClientRect().top,
                        })
                      }
                      onMouseLeave={() => setHover(null)}
                    >
                      {formatTemp(temp)}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        ))}
      </div>

      {unplaced.length > 0 && (
        <div className="mt-6">
          <div className="mb-2 text-xs font-medium text-muted">Unplaced</div>
          <div className="flex flex-wrap gap-2">
            {unplaced.map((s) => {
              const color =
                s.status === "nodata" || s.temperature == null
                  ? STATUS_COLOR.nodata
                  : thermalColor(s.temperature, escalaDe(s.temperature_metric));
              return (
                <button
                  key={s.device.id}
                  onClick={() => navigate(`/devices/${s.device.id}`)}
                  className="flex items-center gap-2 rounded-md border border-border bg-surface2 px-2 py-1 text-xs hover:border-accent/40"
                >
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
                  <span className="text-ink">{s.device.name}</span>
                  <span className="mono text-muted">{formatTemp(s.temperature)}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {hover && (
        <div
          className="pointer-events-none fixed z-50 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs shadow-panel"
          style={{ left: hover.x + 8, top: hover.y }}
        >
          <div className="font-medium text-ink">{hover.s.device.name}</div>
          <div className="mono text-muted">
            {formatTemp(hover.s.temperature)} · {hover.s.status}
          </div>
        </div>
      )}
    </div>
  );
}
