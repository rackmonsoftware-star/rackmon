import { useMemo, useRef, useState } from "react";

import type { Sample } from "../types";
import { type EscalaTermica, thermalColor } from "../lib/thermal";

interface Props {
  samples: Sample[];
  unit?: string;
  height?: number;
  /** When true, colour the stroke by value along the thermal ramp. */
  thermal?: boolean;
  /** Que escala termica usar. Una CPU a 70 grados es aviso y el aire de entrada
      a 27 tambien: pintarlas con la misma rampa hace que una de las dos mienta. */
  escala?: EscalaTermica;
  warn?: number | null;
  crit?: number | null;
}

const PAD = { top: 12, right: 12, bottom: 22, left: 40 };

export default function LineChart({
  samples,
  unit = "",
  height = 240,
  thermal = true,
  escala = "entrada",
  warn = null,
  crit = null,
}: Props) {
  const width = 720; // viewBox width; SVG scales to container
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);

  const geom = useMemo(() => {
    const clean = samples.filter((s) => Number.isFinite(s.v) && Number.isFinite(new Date(s.t).getTime()));
    if (clean.length === 0) return null;
    const xs = clean.map((s) => new Date(s.t).getTime());
    const ys = clean.map((s) => s.v);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    let dataMin = Math.min(...ys);
    let dataMax = Math.max(...ys);
    if (dataMin === dataMax) {
      dataMin -= 1;
      dataMax += 1;
    }
    // "Nice" evenly-spaced ticks: round the domain bounds and the step to a
    // 1/2/5×10ⁿ value so gridline labels are uniform and never skip a number
    // (a naive equal-split + integer-round produces e.g. 30,31,33,34,35).
    const rawStep = (dataMax - dataMin) / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep || 1)));
    const norm = (rawStep || 1) / mag;
    const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : norm >= 1 ? 1 : norm >= 0.5 ? 0.5 : norm >= 0.2 ? 0.2 : 0.1) * mag;
    const yMin = Math.floor(dataMin / step) * step;
    const yMax = Math.ceil(dataMax / step) * step;
    const yTicks: number[] = [];
    for (let v = yMin; v <= yMax + step / 2; v += step) yTicks.push(Math.round(v / step) * step);
    const yDecimals = step < 0.1 ? 2 : step < 1 ? 1 : 0;

    const iw = width - PAD.left - PAD.right;
    const ih = height - PAD.top - PAD.bottom;
    const sx = (t: number) =>
      PAD.left + (xMax === xMin ? iw / 2 : ((t - xMin) / (xMax - xMin)) * iw);
    const sy = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * ih;

    const pts = clean.map((s) => ({
      x: sx(new Date(s.t).getTime()),
      y: sy(s.v),
      v: s.v,
      t: s.t,
    }));
    const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    const area =
      `M${pts[0].x.toFixed(1)},${(PAD.top + ih).toFixed(1)} ` +
      pts.map((p) => `L${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ") +
      ` L${pts[pts.length - 1].x.toFixed(1)},${(PAD.top + ih).toFixed(1)} Z`;

    return { pts, line, area, sx, sy, xMin, xMax, yMin, yMax, iw, ih, yTicks, yDecimals };
  }, [samples, height]);

  if (!geom) {
    return (
      <div
        className="flex items-center justify-center text-sm text-muted"
        style={{ height }}
      >
        No data in range
      </div>
    );
  }

  const last = geom.pts[geom.pts.length - 1];
  const strokeColor = thermal ? thermalColor(last.v, escala) : "#22D3EE";

  // Nearest point to hover
  let hover: (typeof geom.pts)[number] | null = null;
  if (hoverX !== null) {
    let best = Infinity;
    for (const p of geom.pts) {
      const d = Math.abs(p.x - hoverX);
      if (d < best) {
        best = d;
        hover = p;
      }
    }
  }

  const yTickVals = geom.yTicks;

  const fmtTime = (iso: string) =>
    new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const chartLabel = samples.length
    ? `Metric history — ${samples.length} points${unit ? ` (${unit})` : ""}`
    : "Metric history — no data";

  return (
    <div ref={wrapRef} className="relative w-full">
      <svg
        role="img"
        aria-label={chartLabel}
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        preserveAspectRatio="none"
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const rx = ((e.clientX - rect.left) / rect.width) * width;
          setHoverX(rx);
        }}
        onMouseLeave={() => setHoverX(null)}
      >
        <defs>
          <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={strokeColor} stopOpacity="0.28" />
            <stop offset="100%" stopColor={strokeColor} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Y ticks + gridlines */}
        {yTickVals.map((v, i) => {
          const y = geom.sy(v);
          return (
            <g key={i}>
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={y}
                y2={y}
                stroke="var(--border)"
                strokeWidth={1}
                opacity={0.5}
              />
              <text x={PAD.left - 6} y={y + 3} textAnchor="end" fontSize="10" fill="var(--muted)">
                {v.toFixed(geom.yDecimals)}
              </text>
            </g>
          );
        })}

        {/* Threshold guides */}
        {warn != null && warn >= geom.yMin && warn <= geom.yMax && (
          <line
            x1={PAD.left}
            x2={width - PAD.right}
            y1={geom.sy(warn)}
            y2={geom.sy(warn)}
            stroke="#FBBF24"
            strokeWidth={1}
            strokeDasharray="4 4"
            opacity={0.7}
          />
        )}
        {crit != null && crit >= geom.yMin && crit <= geom.yMax && (
          <line
            x1={PAD.left}
            x2={width - PAD.right}
            y1={geom.sy(crit)}
            y2={geom.sy(crit)}
            stroke="#F87171"
            strokeWidth={1}
            strokeDasharray="4 4"
            opacity={0.7}
          />
        )}

        <path d={geom.area} fill="url(#area-grad)" />
        <path
          d={geom.line}
          fill="none"
          stroke={strokeColor}
          strokeWidth={1.8}
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Last point marker */}
        <circle cx={last.x} cy={last.y} r={3} fill={strokeColor} />

        {/* Hover guide */}
        {hover && (
          <g>
            <line
              x1={hover.x}
              x2={hover.x}
              y1={PAD.top}
              y2={height - PAD.bottom}
              stroke="var(--muted)"
              strokeWidth={1}
              opacity={0.6}
            />
            <circle cx={hover.x} cy={hover.y} r={3.5} fill="#fff" stroke={strokeColor} strokeWidth={2} />
          </g>
        )}
      </svg>

      {hover && (
        <div
          className="pointer-events-none absolute z-10 rounded-md border border-border bg-surface2 px-2 py-1 text-xs shadow-panel"
          style={{
            left: `calc(${(hover.x / width) * 100}% )`,
            top: 4,
            transform: "translateX(-50%)",
          }}
        >
          <div className="mono text-ink">
            {hover.v.toFixed(1)}
            {unit}
          </div>
          <div className="text-muted">{fmtTime(hover.t)}</div>
        </div>
      )}
    </div>
  );
}
