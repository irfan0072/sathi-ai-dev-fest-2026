import { useCallback, useEffect, useRef, useState } from 'react';
import Icon from '../Icon';

export const bdt = (v) => (v == null ? '—' : `৳${Math.round(v).toLocaleString('en-US')}`);
export const num = (v) => (v == null ? '—' : Number(v).toLocaleString('en-US'));
export const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(0)}%`);
export const compact = (v) => {
  if (v == null) return '—';
  if (v >= 1e6) return `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(v >= 1e4 ? 0 : 1)}K`;
  return String(v);
};
export const timeAgo = (iso) => {
  if (!iso) return '—';
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 0) {
    const f = -s;
    return f < 60 ? `in ${f}s` : f < 3600 ? `in ${Math.round(f / 60)}m` : `in ${Math.round(f / 3600)}h`;
  }
  if (s < 10) return 'just now';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};
export const when = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

/** Poll a loader every `ms` while the tab is visible. Returns [data, error, reload]. */
export function usePoll(loader, ms = 5000, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const saved = useRef(loader);
  saved.current = loader;
  const reload = useCallback(async () => {
    try {
      const value = await saved.current();
      setData(value);
      setError('');
    } catch (err) {
      setError(err.message);
    }
  }, []);
  useEffect(() => {
    reload();
    if (!ms) return undefined;
    const timer = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState !== 'hidden') reload();
    }, ms);
    return () => clearInterval(timer);
  }, [reload, ms, ...deps]);
  return [data, error, reload, setData];
}

export function Kpi({ icon, label, value, note, tone = '', onClick }) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      onClick={onClick}
      className={`panel text-left shadow-sm transition-colors ${onClick ? 'cursor-pointer hover:border-primary/50 focus-ring' : ''}`}
    >
      <div className="panel-body flex-row items-center gap-3 p-4">
        <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${tone || 'bg-base-200'}`}>
          <Icon name={icon} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="muted truncate">{label}</div>
          <div className="text-xl font-bold leading-tight tabular-nums">{value}</div>
          {note && <div className="muted truncate">{note}</div>}
        </div>
      </div>
    </Tag>
  );
}

export function Panel({ title, action, children, className = '', bodyClass = '' }) {
  return (
    <section className={`panel shadow-sm ${className}`}>
      <div className={`panel-body gap-3 ${bodyClass}`}>
        {(title || action) && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            {title && <h3 className="font-semibold">{title}</h3>}
            {action}
          </div>
        )}
        {children}
      </div>
    </section>
  );
}

export function PageHead({ title, lead, children }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-xl font-bold tracking-tight sm:text-2xl">{title}</h2>
        {lead && <p className="page-lead mt-1 max-w-3xl">{lead}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function LiveDot({ label = 'Live' }) {
  return (
    <span className="flex items-center gap-1.5 text-xs font-medium text-success">
      <span className="relative flex size-2">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
        <span className="relative inline-flex size-2 rounded-full bg-success" />
      </span>
      {label}
    </span>
  );
}

export function Tabs({ items, value, onChange }) {
  return (
    <div role="tablist" className="tabs tabs-box w-fit flex-wrap">
      {items.map((t) => (
        <button
          key={t.id}
          role="tab"
          className={`tab gap-2 ${value === t.id ? 'tab-active' : ''}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
          {t.count != null && <span className="badge badge-sm">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Alert({ kind = 'error', children }) {
  if (!children) return null;
  return <div role="alert" className={`alert alert-${kind} alert-soft text-sm`}>{children}</div>;
}

export function Empty({ icon = 'check', title, body }) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <Icon name={icon} className="size-7 text-base-content/40" />
      <div className="font-medium">{title}</div>
      {body && <div className="muted max-w-sm">{body}</div>}
    </div>
  );
}

export const taskTone = {
  auto: 'badge-info', retry_scheduled: 'badge-warning', needs_manual: 'badge-error',
  assigned: 'badge-secondary', in_progress: 'badge-primary', resolved: 'badge-success',
  ignored: 'badge-ghost',
};
export const taskLabel = {
  auto: 'Calling', retry_scheduled: 'Retry scheduled', needs_manual: 'Needs a person',
  assigned: 'Assigned', in_progress: 'On call', resolved: 'Resolved', ignored: 'Ignored (unreachable)',
};
export const manualReason = {
  unclear_response: 'AI could not understand the answer',
  retries_exhausted: 'No answer after all retries',
  admin_escalated: 'Sent by admin',
  customer_callback: 'Customer asked for a call back',
  customer_requested_human: 'Customer pressed 9 to talk to a person',
  assistant_report: 'Customer reported a problem in the Sathi assistant',
  provider_failure: 'The call could not be placed (provider problem)',
};
// Independent follow-up: the customer may have answered on a handset the agent controls, so a
// registered-number call alone never clears a case.
export const followupLabel = {
  not_required: 'Not needed', required: 'Independent contact needed', attempted: 'Contact attempted',
  reached_independently: 'Reached independently', uncertain: 'Uncertain: still open', unreachable: 'Unreachable: still open',
};
export const followupTone = {
  not_required: 'badge-ghost', required: 'badge-warning', attempted: 'badge-info',
  reached_independently: 'badge-success', uncertain: 'badge-error', unreachable: 'badge-error',
};
export const checkTone = {
  verified: 'badge-success', suspicious: 'badge-error', pending: 'badge-info', calling: 'badge-info',
  no_answer: 'badge-warning', manual_review: 'badge-secondary', unreachable: 'badge-ghost',
};
export const checkText = {
  verified: 'Verified', suspicious: 'Suspicious', pending: 'Waiting', calling: 'Calling',
  no_answer: 'No answer', manual_review: 'Supervisor review', unreachable: 'Unreachable',
};
export const priorityTone = { urgent: 'badge-error', high: 'badge-warning', normal: 'badge-ghost' };

export function Badge({ tone = 'badge-ghost', children }) {
  return <span className={`badge badge-sm whitespace-nowrap ${tone}`}>{children}</span>;
}

/** Minimal bar series for per-minute / per-hour counts with a highlighted overlay. */
export function Bars({ points, value, overlay, label, height = 120, xLabel }) {
  const [hover, setHover] = useState(null);
  const W = 560, H = height, pad = { l: 28, r: 6, t: 8, b: 20 };
  const max = Math.max(1, ...points.map((p) => p[value] || 0));
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const slot = iw / Math.max(points.length, 1), bw = Math.max(2, slot - 3);
  const y = (v) => pad.t + ih - (v / max) * ih;
  return (
    <div className="relative w-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={label}>
        <line x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} stroke="var(--viz-grid)" />
        <line x1={pad.l} x2={W - pad.r} y1={y(max)} y2={y(max)} stroke="var(--viz-grid)" strokeDasharray="3 3" />
        <text x={pad.l - 5} y={y(max) + 4} textAnchor="end" fontSize="10" fill="var(--viz-text)">{max}</text>
        <text x={pad.l - 5} y={y(0) + 4} textAnchor="end" fontSize="10" fill="var(--viz-text)">0</text>
        {points.map((p, i) => {
          const x = pad.l + slot * i + (slot - bw) / 2;
          const v = p[value] || 0;
          const o = overlay ? p[overlay] || 0 : 0;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={pad.l + slot * i} y={pad.t} width={slot} height={ih} fill="transparent" />
              {v > 0 && <rect x={x} y={y(v)} width={bw} height={y(0) - y(v)} rx="1.5" fill="var(--viz-1)" opacity={hover === null || hover === i ? 1 : 0.5} />}
              {o > 0 && <rect x={x} y={y(o)} width={bw} height={y(0) - y(o)} rx="1.5" fill="var(--color-error)" />}
              {xLabel && i % Math.ceil(points.length / 6) === 0 && (
                <text x={x + bw / 2} y={H - 5} textAnchor="middle" fontSize="10" fill="var(--viz-text)">{xLabel(p)}</text>
              )}
            </g>
          );
        })}
      </svg>
      {hover !== null && points[hover] && (
        <div className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2 rounded-box border border-base-300 bg-base-100 px-2 py-1 text-xs shadow">
          {xLabel ? xLabel(points[hover]) : ''} · {points[hover][value] || 0}
          {overlay ? ` · ${points[hover][overlay] || 0} suspicious` : ''}
        </div>
      )}
    </div>
  );
}

export function Pager({ onMore, busy, hasMore }) {
  if (!hasMore) return null;
  return (
    <div className="flex justify-center pt-2">
      <button className="btn btn-sm btn-ghost border-base-300 focus-ring" disabled={busy} onClick={onMore}>
        {busy ? <span className="loading loading-spinner loading-xs" /> : 'Load more'}
      </button>
    </div>
  );
}

/** Small hook for "supervisor picker" lists used by assign menus. */
export function useSupervisors(enabled, api) {
  const [list, setList] = useState([]);
  useEffect(() => {
    if (!enabled) return;
    api.getStaff('supervisor').then((r) => setList(r.items.filter((s) => s.active))).catch(() => setList([]));
  }, [enabled, api]);
  return list;
}

export function AssignMenu({ supervisors, onAssign, label = 'Assign to…', disabled }) {
  return (
    <select
      className="select select-bordered select-sm w-auto focus-ring"
      value=""
      disabled={disabled}
      onChange={(e) => e.target.value && onAssign(e.target.value)}
      aria-label={label}
    >
      <option value="">{label}</option>
      {supervisors.map((s) => (
        <option key={s.staff_id} value={s.staff_id}>
          {s.display_name} ({s.open_calls + s.open_cases} open)
        </option>
      ))}
    </select>
  );
}
