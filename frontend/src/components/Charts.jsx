import { useState } from 'react';

const bdt = (v) => `৳${Math.round(v).toLocaleString('en-US')}`;
const compact = (v) => (v >= 1000 ? `৳${(v / 1000).toLocaleString('en-US', { maximumFractionDigits: 1 })}k` : `৳${Math.round(v)}`);
const niceMax = (v) => {
  if (v <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / mag) * mag;
};

function Tooltip({ x, y, width, children }) {
  const left = Math.min(Math.max(x, 70), width - 70);
  return (
    <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-box border border-base-300 bg-base-100 px-2.5 py-1.5 text-xs shadow-md"
      style={{ left: `${(left / width) * 100}%`, top: y }}>
      {children}
    </div>
  );
}

/** Daily forecast bars (one series) with a P90 tick on each bar. */
export function ForecastChart({ days }) {
  const [hover, setHover] = useState(null);
  const W = 560, H = 220, pad = { l: 52, r: 12, t: 16, b: 28 };
  const max = niceMax(Math.max(...days.map((d) => d.p90_bdt), 1));
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const slot = iw / days.length, bw = Math.min(36, slot * 0.55);
  const y = (v) => pad.t + ih - (v / max) * ih;
  const ticks = [0, max / 2, max];
  return (
    <div className="relative w-full" role="figure">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Seven-day cash-out demand forecast with P90 upper estimate">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth="1" />
            <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--viz-text)">{compact(t)}</text>
          </g>
        ))}
        {days.map((d, i) => {
          const cx = pad.l + slot * i + slot / 2;
          const top = y(d.forecast_bdt);
          const h = Math.max(0, pad.t + ih - top);
          return (
            <g key={d.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={cx - slot / 2} y={pad.t} width={slot} height={ih} fill="transparent" />
              <path d={`M${cx - bw / 2},${pad.t + ih} V${top + Math.min(4, h)} q0,-4 4,-4 H${cx + bw / 2 - 4} q4,0 4,4 V${pad.t + ih} Z`}
                fill="var(--viz-1)" opacity={hover === null || hover === i ? 1 : 0.55} />
              <line x1={cx - bw / 2 - 4} x2={cx + bw / 2 + 4} y1={y(d.p90_bdt)} y2={y(d.p90_bdt)} stroke="var(--viz-text)" strokeWidth="2" strokeLinecap="round" />
              <text x={cx} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--viz-text)">
                {new Date(`${d.date}T00:00:00`).toLocaleDateString('en-US', { weekday: 'short', day: 'numeric' })}
              </text>
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <Tooltip x={pad.l + slot * hover + slot / 2} y={`${(y(days[hover].p90_bdt) / H) * 100}%`} width={W}>
          <div className="font-semibold">{days[hover].date}</div>
          <div>Forecast {bdt(days[hover].forecast_bdt)}</div>
          <div>P90 {bdt(days[hover].p90_bdt)}</div>
        </Tooltip>
      )}
      <div className="muted mt-1 flex flex-wrap gap-4">
        <span className="flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-sm" style={{ background: 'var(--viz-1)' }} />Expected cash needed</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-3" style={{ background: 'var(--viz-text)' }} />On a busy day</span>
      </div>
    </div>
  );
}

const policyStyle = {
  uplift_t_learner: { label: 'Sathi AI', color: 'var(--viz-1)' },
  response_model: { label: 'Usual method', color: 'var(--viz-2)' },
  agent_dependence_rule: { label: 'Simple rule', color: 'var(--viz-3)' },
  random: { label: 'Random pick', color: 'var(--viz-ref)', dashed: true },
};

/** Qini curves: incremental enrollments as more customers are targeted. */
export function QiniChart({ policies }) {
  const [hover, setHover] = useState(null);
  const names = Object.keys(policyStyle).filter((n) => policies[n]);
  const W = 560, H = 260, pad = { l: 44, r: 112, t: 14, b: 32 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const all = names.flatMap((n) => policies[n].curve.map((p) => p.incremental));
  const max = niceMax(Math.max(...all, 1));
  const min = Math.min(0, ...all);
  const x = (s) => pad.l + s * iw;
  const y = (v) => pad.t + ih - ((v - min) / (max - min)) * ih;
  const points = policies[names[0]].curve.length;
  const ends = names.map((n) => ({ n, v: policies[n].curve[points - 1].incremental }));
  // Spread direct labels so they never overlap.
  const labelY = {};
  [...ends].sort((a, b) => y(a.v) - y(b.v)).forEach((e, i, arr) => {
    const prev = i ? labelY[arr[i - 1].n] : -Infinity;
    labelY[e.n] = Math.max(y(e.v), prev + 14);
  });
  return (
    <div className="relative w-full" role="figure">
      <div className="mb-1 flex flex-wrap gap-4 text-xs">
        {names.map((n) => (
          <span key={n} className="flex items-center gap-1.5">
            <svg width="16" height="4" aria-hidden="true"><line x1="0" x2="16" y1="2" y2="2" stroke={policyStyle[n].color} strokeWidth="2" strokeDasharray={policyStyle[n].dashed ? '4 3' : undefined} /></svg>
            {policyStyle[n].label}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Qini curves comparing targeting policies"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const sx = ((e.clientX - r.left) / r.width) * W;
          const idx = Math.round(((sx - pad.l) / iw) * (points - 1));
          setHover(idx >= 0 && idx < points ? idx : null);
        }}>
        {[min, (max + min) / 2, max].map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={pad.l + iw} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--viz-text)">{Math.round(t)}</text>
          </g>
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((s) => (
          <text key={s} x={x(s)} y={H - 10} textAnchor="middle" fontSize="11" fill="var(--viz-text)">{s * 100}%</text>
        ))}
        {names.map((n) => (
          <polyline key={n} fill="none" stroke={policyStyle[n].color} strokeWidth="2" strokeLinejoin="round"
            strokeDasharray={policyStyle[n].dashed ? '5 4' : undefined}
            points={policies[n].curve.map((p) => `${x(p.targeted_share)},${y(p.incremental)}`).join(' ')} />
        ))}
        {names.map((n) => (
          <text key={n} x={pad.l + iw + 8} y={labelY[n] + 4} fontSize="11" fill="var(--viz-text)">{policyStyle[n].label}</text>
        ))}
        {hover !== null && (
          <g>
            <line x1={x(hover / (points - 1))} x2={x(hover / (points - 1))} y1={pad.t} y2={pad.t + ih} stroke="var(--viz-text)" strokeDasharray="2 3" />
            {names.map((n) => (
              <circle key={n} cx={x(hover / (points - 1))} cy={y(policies[n].curve[hover].incremental)} r="4" fill={policyStyle[n].color} stroke="var(--color-base-100)" strokeWidth="2" />
            ))}
          </g>
        )}
      </svg>
      {hover !== null && (
        <Tooltip x={x(hover / (points - 1))} y="20%" width={W}>
          <div className="font-semibold">Inviting the top {Math.round((hover / (points - 1)) * 100)}%</div>
          {names.map((n) => <div key={n}>{policyStyle[n].label}: {policies[n].curve[hover].incremental.toFixed(0)}</div>)}
        </Tooltip>
      )}
      <div className="muted mt-1">Left to right: share of customers invited. Bottom to top: extra people who joined. Higher is better.</div>
    </div>
  );
}

/** Horizontal bars for error comparison (lower is better). */
export function ErrorBars({ rows, format = (v) => v.toFixed(2), highlightLowest = true }) {
  const max = Math.max(...rows.map((r) => r.value), 0.0001);
  const best = highlightLowest ? Math.min(...rows.map((r) => r.value)) : null;
  return (
    <div className="flex flex-col gap-2">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[minmax(0,10rem)_1fr_3.5rem] items-center gap-2 text-xs">
          <span className={`truncate ${r.value === best ? 'font-semibold' : ''}`} title={r.label}>{r.label}</span>
          <div className="h-3 rounded-r" style={{ width: `${(r.value / max) * 100}%`, background: 'var(--viz-1)', opacity: best === null || r.value === best ? 1 : 0.45 }} />
          <span className="text-right font-mono">{format(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** Hourly mandate volume (one series) with confirmed count in the tooltip. */
export function HourlyBars({ hours }) {
  const [hover, setHover] = useState(null);
  const W = 560, H = 160, pad = { l: 30, r: 8, t: 10, b: 24 };
  const now = new Date();
  const slots = Array.from({ length: 24 }, (_, i) => {
    const d = new Date(now); d.setMinutes(0, 0, 0); d.setHours(d.getHours() - 23 + i);
    const hit = hours.find((h) => new Date(h.hour).getTime() === d.getTime());
    return { at: d, mandates: hit?.mandates || 0, confirmed: hit?.confirmed || 0 };
  });
  const max = niceMax(Math.max(...slots.map((s) => s.mandates), 1));
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b, slot = iw / 24, bw = Math.max(4, slot - 4);
  const y = (v) => pad.t + ih - (v / max) * ih;
  return (
    <div className="relative w-full" role="figure">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Cash-outs per hour, last 24 hours">
        {[0, max].map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--viz-text)">{t}</text>
          </g>
        ))}
        {slots.map((s, i) => {
          const x = pad.l + slot * i + (slot - bw) / 2;
          const h = pad.t + ih - y(s.mandates);
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={pad.l + slot * i} y={pad.t} width={slot} height={ih} fill="transparent" />
              {s.mandates > 0 && <rect x={x} y={y(s.mandates)} width={bw} height={h} rx="2" fill="var(--viz-1)" opacity={hover === null || hover === i ? 1 : 0.55} />}
              {i % 6 === 0 && <text x={x + bw / 2} y={H - 6} textAnchor="middle" fontSize="11" fill="var(--viz-text)">{s.at.getHours()}:00</text>}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <Tooltip x={pad.l + slot * hover + slot / 2} y="30%" width={W}>
          <div className="font-semibold">{slots[hover].at.getHours()}:00</div>
          <div>{slots[hover].mandates} cash-outs · {slots[hover].confirmed} verified</div>
        </Tooltip>
      )}
    </div>
  );
}

/** Proportion bar for an ordinal state set (status colors, always labelled). */
export function StateBar({ parts }) {
  const total = parts.reduce((a, p) => a + p.value, 0);
  if (!total) return <p className="muted">Nothing yet today.</p>;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full">
        {parts.filter((p) => p.value > 0).map((p) => (
          <div key={p.label} title={`${p.label}: ${p.value}`} style={{ width: `${(p.value / total) * 100}%`, background: p.color }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {parts.map((p) => (
          <span key={p.label} className="flex items-center gap-1.5">
            <span className="inline-block size-2.5 rounded-sm" style={{ background: p.color }} />
            {p.label} <strong>{p.value}</strong>
          </span>
        ))}
      </div>
    </div>
  );
}
