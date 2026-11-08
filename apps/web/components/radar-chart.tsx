/** Small dependency-free radar chart (SVG). Series values are on 0..max. */
export function RadarChart({
  axes,
  series,
  max,
  size = 240,
  label,
}: {
  axes: string[];
  series: { name: string; values: number[]; color: string; dashed?: boolean }[];
  max: number;
  size?: number;
  label: string;
}) {
  const n = axes.length;
  if (n < 3) return null;
  const c = size / 2;
  const r = size / 2 - 44;
  const pt = (i: number, v: number) => {
    const a = (Math.PI * 2 * i) / n - Math.PI / 2;
    const k = (Math.max(0, Math.min(max, v)) / max) * r;
    return [c + Math.cos(a) * k, c + Math.sin(a) * k] as const;
  };
  const rings = [0.25, 0.5, 0.75, 1];
  return (
    <figure className="flex flex-col items-center">
      <svg viewBox={`0 0 ${size} ${size}`} width="100%" style={{ maxWidth: size }} role="img" aria-label={label}>
        {rings.map((f) => (
          <polygon
            key={f}
            points={axes.map((_, i) => pt(i, f * max).join(",")).join(" ")}
            fill="none"
            stroke="var(--border)"
            strokeWidth={1}
          />
        ))}
        {axes.map((a, i) => {
          const [x, y] = pt(i, max);
          const [lx, ly] = pt(i, max * 1.22);
          return (
            <g key={a}>
              <line x1={c} y1={c} x2={x} y2={y} stroke="var(--border)" strokeWidth={1} />
              <text x={lx} y={ly} fontSize={9} fill="var(--muted)" textAnchor={lx < c - 4 ? "end" : lx > c + 4 ? "start" : "middle"} dominantBaseline="middle">
                {a.length > 16 ? a.slice(0, 15) + "…" : a}
              </text>
            </g>
          );
        })}
        {series.map((s) => (
          <polygon
            key={s.name}
            points={s.values.map((v, i) => pt(i, v).join(",")).join(" ")}
            fill={s.color}
            fillOpacity={s.dashed ? 0 : 0.18}
            stroke={s.color}
            strokeWidth={1.5}
            strokeDasharray={s.dashed ? "4 3" : undefined}
          />
        ))}
      </svg>
      {series.length > 1 && (
        <figcaption className="mt-1 flex gap-3 text-xs text-muted">
          {series.map((s) => (
            <span key={s.name} className="inline-flex items-center gap-1">
              <span className="inline-block h-0.5 w-4" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </figcaption>
      )}
    </figure>
  );
}
