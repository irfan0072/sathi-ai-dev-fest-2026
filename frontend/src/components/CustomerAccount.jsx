import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import { IncomingCall, SmsInbox } from './LiveCall';
import AssistantChat, { CallLanguage } from './AssistantChat';
import { takaFmt } from '../copy';
import { phone } from '../ids';

const customerCheck = {
  waiting: { label: 'Please answer our call', tone: 'badge-info' },
  done: { label: 'Check finished', tone: 'badge-success' },
  missed: { label: 'Missed call', tone: 'badge-warning' },
  unreachable: { label: 'We could not reach you', tone: 'badge-warning' },
  manual: { label: 'A person will contact you', tone: 'badge-secondary' },
};

export default function CustomerAccount() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [phoneKey, setPhoneKey] = useState(0);

  const load = useCallback(async () => {
    try { setData(await api.getMyTransactions()); setError(''); } catch (err) { setError(err.message); }
  }, []);
  useEffect(() => {
    load();
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="page-title">My account</h2>
        <p className="page-lead mt-1">
          After every cash-out, Sathi calls you in your language. Type or say the cash you got and press #. If you did not
          make this cash-out, press * (star). Pressing only # does nothing. Press 9 to talk to a person. Questions? Ask Sathi Sahayak below.
        </p>
      </div>
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="flex flex-col gap-5 lg:col-span-3">
          <div className="panel shadow-sm">
            <div className="panel-body flex-row items-center gap-4">
              <span className="grid size-12 place-items-center rounded-2xl bg-primary/15 text-primary"><Icon name="receipt" /></span>
              <div>
                <div className="muted">Balance</div>
                <div className="text-3xl font-bold">{data ? takaFmt(data.balance) : '…'}</div>
              </div>
            </div>
          </div>

          <div className="panel shadow-sm">
            <div className="panel-body"><AssistantChat onAction={load} /></div>
          </div>

          <div className="panel shadow-sm">
            <div className="panel-body">
              <h3 className="font-semibold">My cash-outs</h3>
              {!data ? <p className="muted">Loading…</p> : data.items.length === 0 ? <p className="muted">No cash-outs yet.</p> : (
                <ul className="divide-y divide-base-300">
                  {data.items.map((t) => (
                    <li key={t.txn_id} className="flex flex-wrap items-center gap-3 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="font-semibold">{takaFmt(t.amount)} <span className="muted font-normal">+ fee {takaFmt(t.fee)}</span></div>
                        <div className="muted">{new Date(t.ts).toLocaleString()} · agent {phone(t.agent_id)} · receipt #{t.txn_id}</div>
                      </div>
                      <span className={`badge badge-sm ${customerCheck[t.check]?.tone}`}>{customerCheck[t.check]?.label || t.check}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-5 lg:col-span-2">
          <div className="panel shadow-sm">
            <div className="panel-body">
              <h3 className="font-semibold">My phone</h3>
              <IncomingCall key={phoneKey} onFinished={() => { load(); setTimeout(() => setPhoneKey((k) => k + 1), 2500); }} />
            </div>
          </div>
          <div className="panel shadow-sm">
            <div className="panel-body"><CallLanguage /></div>
          </div>
          <div className="panel shadow-sm">
            <div className="panel-body"><SmsInbox /></div>
          </div>
        </div>
      </div>
    </div>
  );
}
