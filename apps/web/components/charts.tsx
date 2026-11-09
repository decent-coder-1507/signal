/** Tiny dependency-free SVG charts (line with baseline, vertical bars). Colours come from theme tokens. */

export function LineChart({
  points,
  baseline,
  label,
  height = 120,
}: {
  points: { x: string; y: number }[];
  baseline?: number | null;
  label: string;
  height?: number;
}) {
  const w = 320;
  const h = height;
  const pad = { l: 34, r: 8, t: 8, b: 18 };
  if (!points.length) return <p className="text-xs text-muted">No data yet.</p>;
  const max = Math.max(1, ...points.map((p) => p.y), baseline ?? 0) * 1.1;
  const x = (i: number) => pad.l + (points.length === 1 ? (w - pad.l - pad.r) / 2 : (i / (points.length - 1)) * (w - pad.l - pad.r));
  const y = (v: number) => pad.t + (1 - v / max) * (h - pad.t - pad.b);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join(" ");
  const fmt = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : String(Math.round(v)));
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label={label}>
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={pad.l} x2={w - pad.r} y1={y(max * f)} y2={y(max * f)} stroke="var(--border)" strokeWidth={1} />
          <text x={pad.l - 4} y={y(max * f)} fontSize={9} fill="var(--muted)" textAnchor="end" dominantBaseline="middle">
            {fmt(max * f)}
          </text>
        </g>
      ))}
      {baseline != null && (
        <g>
          <line x1={pad.l} x2={w - pad.r} y1={y(baseline)} y2={y(baseline)} stroke="var(--info)" strokeDasharray="4 3" strokeWidth={1.5} />
          <text x={w - pad.r} y={y(baseline) - 3} fontSize={9} fill="var(--info)" textAnchor="end">
            baseline
          </text>
        </g>
      )}
      <path d={d} fill="none" stroke="var(--signal)" className="glow-mark" strokeWidth={2} strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={i} cx={x(i)} cy={y(p.y)} r={2.5} fill="var(--signal)">
          <title>
            {p.x}: {p.y}
          </title>
        </circle>
      ))}
      <text x={pad.l} y={h - 4} fontSize={9} fill="var(--muted)">
        {points[0].x}
      </text>
      {points.length > 1 && (
        <text x={w - pad.r} y={h - 4} fontSize={9} fill="var(--muted)" textAnchor="end">
          {points[points.length - 1].x}
        </text>
      )}
    </svg>
  );
}

export function BarChart({ bars, label, height = 140, format = (v: number) => v.toFixed(2) }: { bars: { x: string; y: number }[]; label: string; height?: number; format?: (v: number) => string }) {
  const w = 480;
  const h = height;
  const pad = { l: 40, r: 6, t: 8, b: 18 };
  if (!bars.length) return <p className="text-xs text-muted">No data yet.</p>;
  const max = Math.max(...bars.map((b) => b.y), 1e-9) * 1.1;
  const bw = (w - pad.l - pad.r) / bars.length;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label={label}>
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={pad.l} x2={w - pad.r} y1={pad.t + (1 - f) * (h - pad.t - pad.b)} y2={pad.t + (1 - f) * (h - pad.t - pad.b)} stroke="var(--border)" />
          <text x={pad.l - 4} y={pad.t + (1 - f) * (h - pad.t - pad.b)} fontSize={9} fill="var(--muted)" textAnchor="end" dominantBaseline="middle">
            {format(max * f)}
          </text>
        </g>
      ))}
      {bars.map((b, i) => {
        const bh = (b.y / max) * (h - pad.t - pad.b);
        const rw = Math.min(bw * 0.7, 28);
        return (
          <rect
            key={b.x}
            className="glow-mark"
            x={pad.l + i * bw + (bw - rw) / 2}
            y={h - pad.b - bh}
            width={rw}
            height={Math.max(bh, b.y > 0 ? 1 : 0)}
            rx={3}
            fill="var(--signal)"
          >
            <title>
              {b.x}: {format(b.y)}
            </title>
          </rect>
        );
      })}
      <text x={pad.l} y={h - 4} fontSize={9} fill="var(--muted)">
        {bars[0].x}
      </text>
      {bars.length > 1 && (
        <text x={w - pad.r} y={h - 4} fontSize={9} fill="var(--muted)" textAnchor="end">
          {bars[bars.length - 1].x}
        </text>
      )}
    </svg>
  );
}
