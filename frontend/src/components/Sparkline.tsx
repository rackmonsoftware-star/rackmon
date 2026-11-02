interface Props {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}

export default function Sparkline({ values, width = 96, height = 28, color = "#22D3EE" }: Props) {
  const clean = values.filter((v) => Number.isFinite(v));
  if (clean.length < 2) {
    return <svg width={width} height={height} />;
  }
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  const step = width / (clean.length - 1);
  const path = clean
    .map((v, i) => {
      const x = i * step;
      const y = height - ((v - min) / span) * (height - 4) - 2;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} className="overflow-visible">
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}
