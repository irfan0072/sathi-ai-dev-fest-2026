import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import CredentialsPanel from './CredentialsPanel';

const sourceLabel = { override: 'changed here', env: 'set by server', default: 'default' };
const sourceTone = { override: 'badge-primary', env: 'badge-info', default: 'badge-ghost' };
const groupIcon = {
  'Calls and messages': 'phone', 'Safety checks': 'shield', 'AI helper': 'info',
  'Time to respond': 'cases', 'Price estimates': 'receipt',
};
const providerLabels = {
  twilio: 'Twilio phone calls', bd_http_ivr: 'Bangladesh phone provider',
  alpha_sms: 'Alpha SMS', gemini: 'Gemini', openai: 'OpenAI',
};
export const providerLabel = (id) => providerLabels[id] || id;
const fieldName = {
  TWILIO_ACCOUNT_SID: 'Twilio Account SID', TWILIO_AUTH_TOKEN: 'Twilio Auth token',
  TWILIO_FROM_NUMBER: 'Twilio phone number', SATHI_PUBLIC_API_URL: 'Public web address',
  SATHI_BD_IVR_BASE_URL: 'Provider web address', SATHI_BD_IVR_API_KEY: 'Provider API key',
  SATHI_BD_IVR_WEBHOOK_SECRET: 'Provider secret', ALPHA_SMS_API_KEY: 'Alpha SMS API key',
  GEMINI_API_KEY: 'Gemini API key', OPENAI_API_KEY: 'OpenAI API key',
};

function Field({ item, value, onChange, error, editable, onReset }) {
  const id = `setting-${item.key}`;
  let control;
  if (item.type === 'bool') {
    control = (
      <input id={id} type="checkbox" className="toggle toggle-primary" checked={Boolean(value)}
        disabled={!editable} onChange={(e) => onChange(e.target.checked)} />
    );
  } else if (item.type === 'enum') {
    control = (
      <select id={id} className="select select-bordered select-sm w-full sm:w-64" value={value}
        disabled={!editable} onChange={(e) => onChange(e.target.value)}>
        {item.options.map((o) => (
          <option key={o.value} value={o.value} disabled={Boolean(o.unavailable_reason)}>
            {o.label}{o.unavailable_reason ? ' (not configured)' : ''}
          </option>
        ))}
      </select>
    );
  } else {
    const numeric = item.type === 'int' || item.type === 'float';
    control = (
      <label className="input input-bordered input-sm w-full sm:w-64">
        <input id={id} type={numeric ? 'number' : 'text'} className="grow" value={value ?? ''}
          disabled={!editable} min={item.min} max={item.max}
          step={item.type === 'float' ? 'any' : 1}
          onChange={(e) => onChange(numeric && e.target.value !== '' ? Number(e.target.value) : e.target.value)} />
        {item.unit && <span className="text-xs opacity-60">{item.unit}</span>}
      </label>
    );
  }
  const blocked = item.type === 'enum' ? item.options.filter((o) => o.unavailable_reason) : [];
  return (
    <div className={`flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:gap-6 ${error ? 'rounded-box bg-error/5 px-3' : ''}`}>
      <div className="min-w-0 flex-1 sm:max-w-md">
        <label htmlFor={id} className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {item.label}
          <span className={`badge badge-xs ${sourceTone[item.source]}`}>{sourceLabel[item.source]}</span>
        </label>
        <p className="muted mt-0.5">{item.help}</p>
        {item.min !== undefined && <p className="muted">Between {item.min} and {item.max}{item.unit ? ` ${item.unit}` : ''} · normally {String(item.default)}</p>}
        {blocked.map((o) => <p key={o.value} className="muted text-warning">{o.label}: {o.unavailable_reason}</p>)}
        {item.source === 'override' && item.updated_by && (
          <p className="muted">Changed by {item.updated_by} · {new Date(item.updated_at).toLocaleString()}</p>
        )}
        {error && <p role="alert" className="mt-1 text-xs text-error">{error}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2 sm:w-48 sm:justify-end">
        {control}
        {item.source === 'override' && editable && (
          <button className="btn btn-ghost btn-xs" onClick={onReset} title="Go back to the normal value">Reset</button>
        )}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState({});
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [readiness, setReadiness] = useState(null);
  const [readinessError, setReadinessError] = useState('');
  const [probes, setProbes] = useState(null);
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeError, setProbeError] = useState('');

  const load = useCallback(async () => {
    try { setData(await api.getSettings()); setError(''); } catch (err) { setError(err.message); }
  }, []);
  const loadReadiness = useCallback(async () => {
    try { setReadiness(await api.getSettingsReadiness()); setReadinessError(''); } catch (err) { setReadinessError(err.message); }
  }, []);
  useEffect(() => {
    load();
    loadReadiness();
  }, [load, loadReadiness]);

  const runProbe = async (only) => {
    setProbeBusy(true);
    setProbeError('');
    try {
      const data = await api.runSettingsProbe(only);
      setProbes(data);
    } catch (err) {
      setProbeError(err.message);
    } finally {
      setProbeBusy(false);
    }
  };

  const items = useMemo(() => Object.fromEntries((data?.items || []).map((i) => [i.key, i])), [data]);
  const dirty = Object.keys(draft).filter((k) => draft[k] !== items[k]?.value);
  const valueOf = (key) => (key in draft ? draft[key] : items[key]?.value);

  const save = async () => {
    setBusy(true); setMessage(''); setErrors({});
    const changes = Object.fromEntries(dirty.map((k) => [k, draft[k]]));
    try {
      setData(await api.updateSettings(changes));
      setDraft({});
      setMessage(`Saved ${dirty.length} change${dirty.length > 1 ? 's' : ''}. Takes effect immediately and is recorded in the audit log.`);
    } catch (err) {
      setErrors(err.key ? { [err.key]: err.message, form: 'Not saved. Fix the highlighted setting.' } : { form: err.message });
    } finally { setBusy(false); }
  };
  const reset = async (key) => {
    setBusy(true); setMessage('');
    try {
      setData(await api.resetSetting(key));
      setDraft((d) => { const next = { ...d }; delete next[key]; return next; });
      setMessage(`${items[key].label} reset.`);
    } catch (err) { setErrors({ form: err.message }); } finally { setBusy(false); }
  };

  return (
    <div className="flex flex-col gap-5 pb-20">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="page-title">Settings</h2>
          <p className="page-lead">Choose how Sathi calls and messages customers, how strict the safety checks are, and enter your service accounts. Changes work right away and are saved with your name.</p>
        </div>
        {data && (data.editable
          ? <span className="badge badge-success badge-soft gap-1 whitespace-nowrap"><Icon name="check" className="size-3.5" />You can make changes</span>
          : <span className="badge badge-warning badge-soft gap-1 whitespace-nowrap"><Icon name="lock" className="size-3.5" />View only</span>)}
      </div>

      {error && <div role="alert" className="alert alert-error alert-soft text-sm">Unavailable: {error}</div>}
      {message && <div role="status" className="alert alert-success alert-soft text-sm">{message}</div>}
      {errors.form && <div role="alert" className="alert alert-error alert-soft text-sm">{errors.form}</div>}
      {!data && !error && <p className="flex items-center gap-2 text-sm opacity-70"><span className="loading loading-dots loading-sm" />Loading settings…</p>}

      {data && <>
        {data.groups.map((group) => (
          <section key={group} className="panel">
            <div className="panel-body py-2">
              <h3 className="flex items-center gap-2 pt-3 font-semibold">
                <Icon name={groupIcon[group] || 'info'} className="size-4 text-primary" />{group}
              </h3>
              <div className="divide-y divide-base-300">
                {data.items.filter((i) => i.group === group).map((item) => (
                  <Field key={item.key} item={item} value={valueOf(item.key)} editable={data.editable}
                    error={errors[item.key]}
                    onChange={(v) => setDraft((d) => ({ ...d, [item.key]: v }))}
                    onReset={() => reset(item.key)} />
                ))}
              </div>
              {group === 'Price estimates' && (
                <div className="mb-3 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-box bg-base-200 p-3"><div className="muted text-xs">Twilio call</div><div className="mt-1 text-lg font-bold">৳{data.unit_costs.twilio_bdt_per_call}</div></div>
                  <div className="rounded-box bg-base-200 p-3"><div className="muted text-xs">Bangladesh provider call</div><div className="mt-1 text-lg font-bold">৳{data.unit_costs.bd_ivr_bdt_per_call}</div></div>
                  <div className="rounded-box bg-base-200 p-3"><div className="muted text-xs">One SMS</div><div className="mt-1 text-lg font-bold">৳{data.unit_costs.sms_bdt}</div></div>
                </div>
              )}
            </div>
          </section>
        ))}

        <CredentialsPanel status={data.credentials} onChanged={() => { load(); loadReadiness(); }} />

        <section className="panel">
          <div className="panel-body">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <h3 className="flex items-center gap-2 font-semibold">
                  <Icon name="globe" className="size-4 text-primary" />Ready to go live?
                </h3>
                <p className="muted mt-1">Shows what is still missing for the services you picked. Press <em>Check all connections</em> to make sure each service accepts your account details.</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {readiness && (readiness.all_ready
                  ? <span className="badge badge-success badge-soft gap-1 whitespace-nowrap"><Icon name="check" className="size-3.5" />Everything you picked is ready</span>
                  : <span className="badge badge-warning badge-soft gap-1 whitespace-nowrap"><Icon name="warning" className="size-3.5" />Some details are missing</span>)}
                <button className="btn btn-ghost btn-sm focus-ring whitespace-nowrap" disabled={probeBusy} onClick={() => runProbe()}>
                  {probeBusy ? <span className="loading loading-spinner loading-xs" /> : <Icon name="play" className="size-4" />}
                  Check all connections
                </button>
              </div>
            </div>

            {readinessError && <div role="alert" className="alert alert-error alert-soft mt-3 text-sm">Unavailable: {readinessError}</div>}
            {probeError && <div role="alert" className="alert alert-error alert-soft mt-3 text-sm">Probe failed: {probeError}</div>}

            {readiness && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {readiness.panels.map((p) => {
                  const probe = probes?.probes?.find((x) => x.name === p.provider_id);
                  return (
                    <div key={p.provider_id}
                         className={`flex h-full flex-col rounded-box border p-4 ${
                           p.selected
                             ? (p.ready ? 'border-success/40 bg-success/5' : 'border-warning/40 bg-warning/5')
                             : 'border-base-300 bg-base-200/40 opacity-70'}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold">{providerLabel(p.provider_id)}</span>
                        {p.selected ? (
                          p.ready
                            ? <span className="badge badge-success badge-xs">ready</span>
                            : <span className="badge badge-warning badge-xs">details missing</span>
                        ) : <span className="badge badge-ghost badge-xs">not in use</span>}
                        {!p.vendor_confirmed && (
                          <span className="badge badge-info badge-xs">provider not signed yet</span>
                        )}
                      </div>
                      <p className="muted mt-2 min-h-8 text-xs">{p.hint}</p>
                      <ul className="mt-2 flex flex-col gap-1 text-xs">
                        {p.env_vars.map((v) => (
                          <li key={v.name} className="flex items-center gap-2">
                            {v.set
                              ? <Icon name="check" className="size-3.5 shrink-0 text-success" />
                              : <Icon name="x" className="size-3.5 shrink-0 text-error" />}
                            <span className={v.set ? '' : 'text-error'}>{fieldName[v.name] || v.name}</span>
                          </li>
                        ))}
                      </ul>
                      {probe && (
                        <div className={`mt-3 rounded-box p-2 text-xs ${
                          probe.probe_ok === true ? 'bg-success/10'
                          : probe.probe_ok === false ? 'bg-error/10'
                          : 'bg-base-200'}`}>
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">
                              {probe.probe_ok === true ? 'Connected'
                                : probe.probe_ok === false ? 'Not working'
                                : 'Not checked (details missing)'}
                            </span>
                            <button className="btn btn-ghost btn-xs focus-ring"
                              disabled={probeBusy} onClick={() => runProbe(p.provider_id)}>
                              Check again
                            </button>
                          </div>
                          <p className="muted mt-1 break-words">{probe.detail}</p>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {!readiness && !readinessError && (
              <p className="mt-3 flex items-center gap-2 text-sm opacity-70">
                <span className="loading loading-dots loading-sm" />Checking…
              </p>
            )}
          </div>
        </section>
      </>}

      {data?.editable && dirty.length > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-base-300 bg-base-100/95 px-4 py-3 backdrop-blur lg:left-72">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
            <span className="text-sm"><strong>{dirty.length}</strong> change{dirty.length > 1 ? 's' : ''} not saved yet</span>
            <div className="flex items-center gap-2">
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => { setDraft({}); setErrors({}); }}>Discard</button>
              <button className="btn btn-primary btn-sm" disabled={busy} onClick={save}>
                {busy && <span className="loading loading-spinner loading-xs" />}Save changes
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
