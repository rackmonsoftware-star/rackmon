import { useMemo } from "react";

import type { Sample } from "../types";

export interface CompareSeries {
  name: string;
  color: string;
  samples: Sample[];
}

interface Props {
  series: CompareSeries[];
  unit?: string;
  height?: number;
  emptyLabel?: string;
}

const PAD = { top: 12, right: 12, bottom: 24, left: 44 };

export default function MultiLineChart({ series, unit = "", height = 300, emptyLabel = "Select devices to compare" }: Props) {
  const width = 760;

  const geom = useMemo(() => {
    const clean = series
      .map((s) => ({ ...s, samples: s.samples.filter((p) => Number.isFinite(p.v) && Number.isFinite(new Date(p.t).getTime())) }))
      .filter((s) => s.samples.length > 0);
    const all = clean.flatMap((s) => s.samples);
    if (all.length === 0) return null;
    const xs = all.map((s) => new Date(s.t).getTime());
    const ys = all.map((s) => s.v);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    let dataMin = Math.min(...ys);
    let dataMax = Math.max(...ys);
    if (dataMin === dataMax) {
      dataMin -= 1;
      dataMax += 1;
    }
    // "Nice" evenly-spaced ticks (round bounds + 1/2/5×10ⁿ step) so labels never
    // skip a number or space unevenly.
    const rawStep = (dataMax - dataMin) / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep || 1)));
    const norm = (rawStep || 1) / mag;
    const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : norm >= 1 ? 1 : norm >= 0.5 ? 0.5 : norm >= 0.2 ? 0.2 : 0.1) * mag;
    const yMin = Math.floor(dataMin / step) * step;
    const yMax = Math.ceil(dataMax / step) * step;
    const yDecimals = step < 0.1 ? 2 : step < 1 ? 1 : 0;

    const iw = width - PAD.left - PAD.right;
    const ih = height - PAD.top - PAD.bottom;
    const sx = (t: number) => PAD.left + (xMax === xMin ? iw / 2 : ((t - xMin) / (xMax - xMin)) * iw);
    const sy = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * ih;

    const paths = clean.map((s) => ({
      color: s.color,
      name: s.name,
      d: s.samples
        .map((p, i) => `${i === 0 ? "M" : "L"}${sx(new Date(p.t).getTime()).toFixed(1)},${sy(p.v).toFixed(1)}`)
        .join(" "),
    }));

    const ticks: number[] = [];
    for (let v = yMin; v <= yMax + step / 2; v += step) ticks.push(Math.round(v / step) * step);
    const yTicks = ticks.map((v) => ({ v, y: sy(v) }));

    return { paths, yTicks, yDecimals };
  }, [series, height]);

  if (!geom) {
    return (
      <div className="flex items-center justify-center text-sm text-muted" style={{ height }}>
        {emptyLabel}
      </div>
    );
  }

  return (
    <div className="w-full">
      <svg role="img" aria-label={`Comparison chart — ${series.map((s) => s.name).join(", ")}${unit ? ` (${unit})` : ""}`} viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
        {geom.yTicks.map((tk, i) => (
          <g key={i}>
            <line x1={PAD.left} x2={width - PAD.right} y1={tk.y} y2={tk.y} stroke="var(--border)" strokeWidth={1} opacity={0.5} />
            <text x={PAD.left - 6} y={tk.y + 3} textAnchor="end" fontSize="10" fill="var(--muted)">
              {tk.v.toFixed(geom.yDecimals)}
            </text>
          </g>
        ))}
        {geom.paths.map((p, i) => (
          <path key={i} d={p.d} fill="none" stroke={p.color} strokeWidth={1.8} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3">
        {series.map((s) => (
          <span key={s.name} className="flex items-center gap-1.5 text-xs text-muted">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
        {unit && <span className="text-xs text-muted">({unit})</span>}
      </div>
    </div>
  );
}
