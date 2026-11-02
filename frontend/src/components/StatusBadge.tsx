import type { DeviceStatusKind } from "../types";
import { STATUS_COLOR } from "../lib/thermal";
import { usePrefs } from "../prefs";

const LABEL_KEY: Record<DeviceStatusKind, string> = {
  ok: "nominal",
  warning: "warning",
  critical: "critical",
  nodata: "noData",
  maintenance: "maintenance",
};

// Darker, saturated text colors for the light theme so status labels clear
// WCAG AA on white (the bright dot still encodes status by hue).
const INK_LIGHT: Record<DeviceStatusKind, string> = {
  ok: "#047857",
  warning: "#B45309",
  critical: "#B91C1C",
  nodata: "#475569",
  maintenance: "#0369A1",
};

export default function StatusBadge({ status }: { status: DeviceStatusKind }) {
  const { t, theme } = usePrefs();
  const color = STATUS_COLOR[status];
  const light = theme === "light";
  const text = light ? INK_LIGHT[status] : color;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold"
      style={{ color: text, background: `${color}${light ? "24" : "1a"}`, border: `1px solid ${color}${light ? "5a" : "40"}` }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{
          background: color,
          animation:
            status === "critical" ? "pulse2 1.6s ease-in-out infinite" : undefined,
        }}
      />
      {t(LABEL_KEY[status])}
    </span>
  );
}
