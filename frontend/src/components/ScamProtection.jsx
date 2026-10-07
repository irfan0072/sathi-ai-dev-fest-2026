import { useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import { Alert, Badge, Empty, Kpi, LiveDot, PageHead, Panel, Tabs, bdt, timeAgo, usePoll } from './ops/kit';
import { phone } from '../ids';

const levelStyle = {
  high: { box: 'border-error/50 bg-error/10', badge: 'badge-error', title: 'Please check carefully before you send' },
  caution: { box: 'border-warning/60 bg-warning/10', badge: 'badge-warning', title: 'Be careful with this number' },
  none: { box: 'border-base-300 bg-base-200/60', badge: 'badge-ghost', title: 'No community alerts found (this is not a safety guarantee)' },
};
const ID_TYPES = [
  ['upay_number', 'upay number'], ['facebook', 'Facebook page'], ['instagram', 'Instagram'],
  ['whatsapp', 'WhatsApp'], ['telegram', 'Telegram'], ['website', 'Website'], ['other', 'Other'],
];
const CATEGORIES = [
  ['not_delivered', 'Paid but the product never came'], ['fake_product', 'Fake or very different product'],
  ['advance_fee', 'Took advance payment, then disappeared'], ['impersonation', 'Pretended to be upay, a bank or a known shop'],
  ['investment', 'Fake investment / double your money'], ['job_offer', 'Fake job or training fee'], ['other', 'Other'],
];

function RiskBox({ check }) {
  if (!check) return null;
  const style = levelStyle[check.warning_level] || levelStyle.none;
  return (
    <div className={`flex flex-col gap-2 rounded-box border p-4 ${style.box}`} role="status">
      <div className="flex flex-wrap items-center gap-2">
        <Icon name={check.warning_level === 'none' ? 'info' : 'warning'} className="size-5" />
        <strong>{check.advisory?.title || style.title}</strong>
        <span className="font-mono text-sm">{check.masked}</span>
        {check.paid_before && <Badge tone="badge-ghost">you paid before</Badge>}
      </div>
      {check.advisory && (
        <div className="ml-7 flex flex-col gap-1 text-sm">
          <p>{check.advisory.message}</p>
          <p lang="bn" className="font-bangla">{check.advisory.message_bn}</p>
          <ul className="list-disc pl-5">
            {check.advisory.tips.map((t, i) => <li key={t}>{t} <span lang="bn" className="muted font-bangla">· {check.advisory.tips_bn?.[i]}</span></li>)}
          </ul>
          <span className="muted text-xs">Written by {check.advisory.source === 'template' ? 'Sathi' : 'Sathi AI'} from community alerts. These are reports by other customers, not a final decision.</span>
        </div>
      )}
      {check.warnings?.length > 0 && (
        <ul className="ml-7 list-disc text-sm">{check.warnings.filter((w) => !check.advisory || !w.includes('community alerts')).map((w) => <li key={w}>{w}</li>)}</ul>
      )}
      {check.community_reports > 0 && !check.advisory && (
        <p className="ml-7 text-sm">{check.community_reports} community report(s){check.verified_reports ? `, ${check.verified_reports} verified by upay` : ''}.</p>
      )}
      {check.advice && !check.advisory && <p className="ml-7 text-sm font-medium">{check.advice}</p>}
      {!check.exists && <p className="ml-7 text-sm">No upay account uses this number.</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------- send money
export function SendMoney() {
  const [number, setNumber] = useState('');
  const [amount, setAmount] = useState('');
  const [reference, setReference] = useState('');
  const [check, setCheck] = useState(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);
  const [wallet, , reloadWallet] = usePoll(() => api.getMyWallet(), 15000);

  const verify = async () => {
    setError(''); setCheck(null); setAck(false); setDone(null);
    if (!number.trim()) return;
    setBusy(true);
    try { setCheck(await api.checkRecipient(number)); } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  const send = async (e) => {
    e.preventDefault(); setError(''); setBusy(true);
    try {
      const r = await api.sendMoney({ number, amount, reference: reference || null, acknowledged_warning: ack });
      setDone(r); setAmount(''); setReference(''); setCheck(null); setAck(false); reloadWallet();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  const needsAck = check?.warning_level === 'high';
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Send money" lead="Sathi checks every number before you pay, using community reports and payment patterns. Personal accounts are not allowed to sell products, so be careful with online sellers." />
      <div className="grid gap-5 lg:grid-cols-5">
        <Panel className="lg:col-span-3" title="New payment">
          <form onSubmit={send} className="flex flex-col gap-4">
            <label className="form-control">
              <span className="mb-1 text-sm font-medium">Receiver&apos;s upay number</span>
              <div className="join w-full">
                <input className="input input-bordered join-item w-full font-mono focus-ring" inputMode="tel" placeholder="01XXXXXXXXX"
                  value={number} onChange={(e) => { setNumber(e.target.value); setCheck(null); }} onBlur={verify} required />
                <button type="button" className="btn join-item" onClick={verify} disabled={busy || !number.trim()}>Check</button>
              </div>
            </label>
            {!check && <p className="muted -mt-2 text-xs">Demo numbers: 01900000500 (in community alerts) · 01900000600 (home bakery on a personal account) · 01901000002 (ordinary customer).</p>}
            <RiskBox check={check} />
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="form-control">
                <span className="mb-1 text-sm font-medium">Amount (৳)</span>
                <input className="input input-bordered w-full font-mono focus-ring" inputMode="decimal" required value={amount}
                  onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ''))} placeholder="500" />
              </label>
              <label className="form-control">
                <span className="mb-1 text-sm font-medium">Reference (optional)</span>
                <input className="input input-bordered w-full focus-ring" maxLength={80} value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Rent, family…" />
              </label>
            </div>
            {needsAck && (
              <label className="flex cursor-pointer items-start gap-2 rounded-box border border-error/40 p-3 text-sm">
                <input type="checkbox" className="checkbox checkbox-error checkbox-sm mt-0.5" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                I read the warning. I know this person and still want to send money.
              </label>
            )}
            <Alert>{error}</Alert>
            {done && <Alert kind="success">Sent {bdt(done.amount)} to {done.to}. New balance {bdt(done.balance_after)}.</Alert>}
            <button className="btn btn-primary focus-ring" disabled={busy || !check || !check.exists || check.is_self || (needsAck && !ack)}>
              {busy ? <span className="loading loading-spinner loading-sm" /> : 'Send money'}
            </button>
            <p className="muted text-xs">Sathi never blocks your money. Warnings are advice from community alerts and payment patterns; you decide.</p>
          </form>
        </Panel>
        <Panel className="lg:col-span-2" title="Recent transfers" action={wallet?.upay_number && <span className="muted font-mono text-xs">your number {wallet.upay_number}</span>}>
          {!wallet ? <span className="loading loading-dots loading-sm" /> : wallet.transfers.length === 0 ? <p className="muted">No transfers yet.</p> : (
            <ul className="divide-y divide-base-300">
              {wallet.transfers.map((t) => (
                <li key={t.transfer_id} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <span className="min-w-0">
                    <span className={`font-medium ${t.direction === 'sent' ? '' : 'text-success'}`}>{t.direction === 'sent' ? 'To' : 'From'} {t.other}</span>
                    <span className="muted block truncate text-xs">{t.reference || '—'} · {timeAgo(t.at)}</span>
                  </span>
                  <span className={`shrink-0 font-semibold tabular-nums ${t.direction === 'sent' ? '' : 'text-success'}`}>{t.direction === 'sent' ? '−' : '+'}{bdt(t.amount)}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- community
function ReportCard({ r, onMeToo }) {
  return (
    <article className="flex flex-col gap-2 rounded-box border border-base-300 bg-base-100 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono font-semibold">{r.identifier}</span>
        <Badge tone="badge-ghost">{ID_TYPES.find(([k]) => k === r.type)?.[1] || r.type}</Badge>
        {r.status === 'verified' ? <Badge tone="badge-error">Verified by upay</Badge> : <Badge tone="badge-ghost">Unverified</Badge>}
        <span className="muted ml-auto text-xs">{timeAgo(r.posted_at)}</span>
      </div>
      <div className="text-sm font-medium">{r.category_text}{r.amount_lost ? ` · lost ${bdt(r.amount_lost)}` : ''}</div>
      <p className="text-sm text-base-content/80">{r.description}</p>
      <div className="flex items-center justify-between gap-2">
        <span className="muted text-xs">Posted anonymously{r.mine ? ' · your report' : ''}</span>
        {!r.mine && (
          <button className={`btn btn-xs focus-ring ${r.i_also ? 'btn-disabled' : 'btn-ghost border-base-300'}`} onClick={() => onMeToo(r.report_id)} disabled={r.i_also}>
            {r.i_also ? 'You added yours' : 'This happened to me too'} · {r.me_too}
          </button>
        )}
      </div>
    </article>
  );
}

function ReportForm({ onDone, preset }) {
  const [form, setForm] = useState({ identifier_type: 'upay_number', identifier: preset || '', category: 'not_delivered', amount_lost: '', incident_date: '', description: '', paid_via_upay: true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setError('');
    try {
      await api.reportScam({ ...form, amount_lost: form.amount_lost || null, incident_date: form.incident_date || null });
      onDone();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="form-control">
          <span className="mb-1 text-xs font-medium">Where did you pay or meet them?</span>
          <select className="select select-bordered select-sm w-full focus-ring" value={form.identifier_type} onChange={set('identifier_type')}>
            {ID_TYPES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="form-control sm:col-span-2">
          <span className="mb-1 text-xs font-medium">Number, page or link</span>
          <input required className="input input-bordered input-sm w-full font-mono focus-ring" value={form.identifier} onChange={set('identifier')}
            placeholder={form.identifier_type === 'upay_number' || form.identifier_type === 'whatsapp' ? '01XXXXXXXXX' : 'facebook.com/page-name'} />
        </label>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="form-control sm:col-span-2">
          <span className="mb-1 text-xs font-medium">What happened?</span>
          <select className="select select-bordered select-sm w-full focus-ring" value={form.category} onChange={set('category')}>
            {CATEGORIES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="form-control">
          <span className="mb-1 text-xs font-medium">Amount lost (৳, optional)</span>
          <input className="input input-bordered input-sm w-full font-mono focus-ring" inputMode="decimal" value={form.amount_lost} onChange={set('amount_lost')} />
        </label>
      </div>
      <label className="form-control">
        <span className="mb-1 text-xs font-medium">Describe it (10–1000 letters). Don&apos;t include your own phone, PIN or name.</span>
        <textarea required minLength={10} maxLength={1000} rows={3} className="textarea textarea-bordered text-sm focus-ring" value={form.description} onChange={set('description')} />
      </label>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="checkbox checkbox-sm" checked={form.paid_via_upay} onChange={set('paid_via_upay')} />I paid with upay</label>
        <label className="flex items-center gap-2 text-sm">Date
          <input type="date" className="input input-bordered input-sm focus-ring" value={form.incident_date} onChange={set('incident_date')} max={new Date().toISOString().slice(0, 10)} />
        </label>
      </div>
      <Alert>{error}</Alert>
      <div className="flex items-center justify-between gap-3">
        <p className="muted text-xs">Your name and number are not shown to other customers and the record keeps only a keyed hash of the reporter. That is pseudonymous, not an absolute guarantee: whoever holds the system key and the data could in principle link a report.</p>
        <button className="btn btn-primary btn-sm focus-ring" disabled={busy}>Post report</button>
      </div>
    </form>
  );
}

export function CommunityPage() {
  const [tab, setTab] = useState('check');
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [flash, setFlash] = useState('');
  const [feed, , reloadFeed] = usePoll(() => api.getCommunityFeed(), 20000);
  const [mine, setMine] = useState(null);
  useEffect(() => { if (tab === 'mine') api.getMyReports().then((r) => setMine(r.reports)).catch(() => setMine([])); }, [tab]);

  const search = async (e) => {
    e?.preventDefault(); setError(''); setResult(null);
    if (!query.trim()) return;
    try { setResult(await api.searchCommunity(query)); } catch (err) { setError(err.message); }
  };
  const meToo = async (id) => {
    try { await api.meToo(id); reloadFeed(); if (result) search(); } catch (err) { setError(err.message); }
  };
  const style = result ? levelStyle[result.level] : null;
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Scam alerts" lead="Check a seller before you pay, and warn others anonymously. Personal upay accounts are not allowed to sell products: if a social-media shop asks you to pay a personal number in advance, be careful." />
      {feed && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Kpi icon="warning" label="Reports in the last 30 days" value={feed.stats_30d.reports} tone="bg-error/15 text-error" />
          <Kpi icon="receipt" label="Money reported lost" value={bdt(feed.stats_30d.amount_lost)} />
          <Kpi icon="shield" label="Your identity" value="Not shown" note="Pseudonymous reports" tone="bg-success/15 text-success" />
        </div>
      )}
      <Tabs items={[{ id: 'check', label: 'Check a seller' }, { id: 'report', label: 'Report a scam' }, { id: 'mine', label: 'My reports' }]} value={tab} onChange={setTab} />
      <Alert kind="success">{flash}</Alert>
      <Alert>{error}</Alert>
      {tab === 'check' && (
        <div className="grid gap-5 lg:grid-cols-5">
          <div className="flex flex-col gap-4 lg:col-span-3">
            <Panel>
              <form onSubmit={search} className="join w-full">
                <input className="input input-bordered join-item w-full focus-ring" value={query} onChange={(e) => setQuery(e.target.value)}
                  placeholder="upay number, Facebook page link, website…" aria-label="Seller to check" />
                <button className="btn btn-primary join-item">Check</button>
              </form>
              {result && (
                <div className={`flex flex-col gap-1 rounded-box border p-4 ${style.box}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <Icon name={result.level === 'none' ? 'check' : 'warning'} className="size-5" />
                    <strong>{style.title.replace('this number', result.type === 'upay_number' ? 'this number' : 'this seller')}</strong>
                    <span className="font-mono text-sm">{result.query}</span>
                  </div>
                  <p className="ml-7 text-sm">
                    {result.report_count} report(s){result.verified_count ? `, ${result.verified_count} verified by upay` : ''}{result.me_too ? `, ${result.me_too} people said it happened to them too` : ''}.
                    {result.payment_pattern_flag ? ' Payments to this number also look unusual.' : ''}
                  </p>
                  <p className="muted ml-7 text-xs">{result.note}</p>
                </div>
              )}
            </Panel>
            {result?.reports?.length > 0 && result.reports.map((r) => <ReportCard key={r.report_id} r={r} onMeToo={meToo} />)}
            {!result && (
              <Panel title="Latest community reports" action={<LiveDot />}>
                {!feed ? <span className="loading loading-dots loading-sm" /> : feed.reports.length === 0 ? <Empty title="No reports yet" /> : (
                  <div className="flex flex-col gap-3">{feed.reports.slice(0, 10).map((r) => <ReportCard key={r.report_id} r={r} onMeToo={meToo} />)}</div>
                )}
              </Panel>
            )}
          </div>
          <div className="flex flex-col gap-4 lg:col-span-2">
            <Panel title="Most reported (30 days)">
              {(feed?.most_reported || []).length === 0 ? <p className="muted">Nothing yet.</p> : (
                <ul className="divide-y divide-base-300">
                  {feed.most_reported.map((m) => (
                    <li key={`${m.type}-${m.identifier}`} className="flex items-center justify-between gap-2 py-2 text-sm">
                      <span className="min-w-0 truncate font-mono">{m.identifier}</span>
                      <span className="flex shrink-0 items-center gap-1">
                        {m.verified > 0 && <Badge tone="badge-error">verified</Badge>}
                        <Badge tone="badge-ghost">{m.reports + m.me_too}</Badge>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Stay safe">
              <ul className="ml-4 list-disc text-sm leading-relaxed">
                <li>Prefer cash on delivery from online pages.</li>
                <li>Never pay an advance to a personal number you don&apos;t know.</li>
                <li>upay never asks for your PIN or OTP.</li>
                <li>Too cheap to be true usually is.</li>
              </ul>
            </Panel>
          </div>
        </div>
      )}
      {tab === 'report' && (
        <Panel title="Report a scam seller">
          <ReportForm onDone={() => { setFlash('Thank you. Your anonymous report is now visible to other customers.'); setTab('check'); reloadFeed(); }} />
        </Panel>
      )}
      {tab === 'mine' && (
        <div className="flex flex-col gap-3">
          {!mine ? <span className="loading loading-dots loading-sm" /> : mine.length === 0 ? <Panel><Empty title="You have not posted any reports" /></Panel> : mine.map((r) => <ReportCard key={r.report_id} r={r} onMeToo={meToo} />)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------- staff
export function ScamWatch({ session }) {
  const [tab, setTab] = useState('receivers');
  const [data, error, reload] = usePoll(() => api.getFlaggedReceivers(), 10000);
  const [status, setStatus] = useState('published');
  const [queue, qError, reloadQueue] = usePoll(() => api.getModerationQueue(status), 15000, [status]);
  const [flash, setFlash] = useState('');
  const canModerate = ['supervisor', 'super_admin'].includes(session.role);
  const moderate = async (id, decision) => {
    const note = decision === 'verified' ? window.prompt('How was it verified? (optional)') || '' : '';
    try { await api.moderateReport(id, decision, note); setFlash(`Report #${id} marked ${decision}.`); reloadQueue(); reload(); }
    catch (err) { setFlash(err.message); }
  };
  const levels = data?.levels || {};
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Scam watch" lead="Personal accounts used like shops or scams: many strangers paying the same amount in a short time, money moved out quickly, and community reports. Payers are warned; supervisors review; money is never blocked automatically.">
        <LiveDot />
      </PageHead>
      <Alert kind="info">{flash}</Alert>
      <Alert>{error || qError}</Alert>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon="warning" label="High risk receivers" value={levels.high || 0} tone="bg-error/15 text-error" />
        <Kpi icon="radar" label="Caution / watch" value={(levels.caution || 0) + (levels.watch || 0)} tone="bg-warning/20 text-warning-content" />
        <Kpi icon="arrow" label="P2P transfers, 24h" value={(data?.p2p_24h.transfers || 0).toLocaleString()} note={bdt(data?.p2p_24h.amount)} />
        <Kpi icon="users" label="Reports to moderate" value={status === 'published' ? queue?.reports?.length ?? '—' : '—'} />
      </div>
      <Tabs items={[{ id: 'receivers', label: 'Flagged personal accounts' }, { id: 'community', label: 'Community reports' }]} value={tab} onChange={setTab} />
      {tab === 'receivers' && (
        <div className="grid gap-3 lg:grid-cols-2">
          {(data?.receivers || []).length === 0 && <Panel><Empty title="No flagged accounts right now" /></Panel>}
          {(data?.receivers || []).map((r) => (
            <Panel key={r.user_id}
              title={<span className="flex flex-wrap items-center gap-2"><span className="font-mono">{r.upay_number}</span>
                <Badge tone={r.level === 'high' ? 'badge-error' : r.level === 'caution' ? 'badge-warning' : 'badge-ghost'}>{r.level} · {(r.score * 100).toFixed(0)}%</Badge>
                <Badge tone="badge-ghost">{r.features.kind === 'possible_scam' ? 'possible scam' : 'selling on personal account'}</Badge></span>}
              action={r.case_id && <span className="muted text-xs">case #{r.case_id} · {r.case_status}</span>}>
              <ul className="ml-4 list-disc text-sm">{r.reasons.map((x) => <li key={x.signal}>{x.text}</li>)}</ul>
              <div className="muted grid grid-cols-3 gap-2 text-xs">
                <span>{r.features.inbound_24h} payments</span><span>{r.features.senders} payers</span><span>{bdt(r.features.total_bdt)} in 24h</span>
              </div>
              <div className="muted text-xs">Wallet {phone(r.user_id)} · flagged {timeAgo(r.first_flagged_at)} · updated {timeAgo(r.updated_at)}</div>
            </Panel>
          ))}
        </div>
      )}
      {tab === 'community' && (
        <div className="flex flex-col gap-3">
          <Tabs items={['published', 'verified', 'rejected', 'hidden'].map((s) => ({ id: s, label: s === 'published' ? 'To review' : s[0].toUpperCase() + s.slice(1) }))} value={status} onChange={setStatus} />
          {(queue?.reports || []).length === 0 && <Panel><Empty title="Nothing here" /></Panel>}
          {(queue?.reports || []).map((r) => (
            <Panel key={r.report_id}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono font-semibold">{r.identifier}</span>
                <Badge tone="badge-ghost">{r.type}</Badge>
                <Badge tone="badge-ghost">{r.reports_for_identifier} report(s) · {r.me_too} me-too</Badge>
                {r.payment_flag && <Badge tone="badge-warning">payments flagged: {r.payment_flag}</Badge>}
                <span className="muted ml-auto text-xs">{timeAgo(r.posted_at)}</span>
              </div>
              <div className="text-sm font-medium">{r.category_text}{r.amount_lost ? ` · lost ${bdt(r.amount_lost)}` : ''}</div>
              <p className="text-sm">{r.description}</p>
              {r.note && <p className="muted text-xs">Note: {r.note} ({r.moderated_by})</p>}
              {canModerate && (
                <div className="flex flex-wrap gap-2">
                  {r.status !== 'verified' && <button className="btn btn-xs btn-error focus-ring" onClick={() => moderate(r.report_id, 'verified')}>Verify</button>}
                  {r.status !== 'rejected' && <button className="btn btn-xs btn-ghost border-base-300 focus-ring" onClick={() => moderate(r.report_id, 'rejected')}>Reject</button>}
                  {r.status !== 'hidden' && <button className="btn btn-xs btn-ghost border-base-300 focus-ring" onClick={() => moderate(r.report_id, 'hidden')}>Hide (abuse)</button>}
                  {r.status !== 'published' && <button className="btn btn-xs btn-ghost border-base-300 focus-ring" onClick={() => moderate(r.report_id, 'published')}>Restore</button>}
                </div>
              )}
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
