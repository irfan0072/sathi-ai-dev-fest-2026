import { useEffect, useState } from 'react';
import { api } from '../api';

const rate = (r) => (r && r.denominator ? `${r.numerator}/${r.denominator} (${(r.rate * 100).toFixed(1)}%)` : 'n/a');
const ci = (r) => (r?.ci95 ? ` [${(r.ci95[0] * 100).toFixed(0)}–${(r.ci95[1] * 100).toFixed(0)}%]` : '');
const SHOW = ['rule_baseline', 'ensemble_v1', 'ensemble_v2_shortfall'];

// Compact, read-only view of the hash-verified extended benchmark (v2). Synthetic evidence.
export function ExtendedBenchmarkView({ data }) {
  const h = data.final_held_out;
  const subtle = data.scenarios.find((s) => s.scenario === 'subtle');
  const subtleRecall = subtle?.methods.ensemble_v1.recall;
  return (
    <div className="flex flex-col gap-4" data-testid="extended-benchmark">
      <div className="rounded-box border border-warning/50 bg-warning/10 p-3 text-sm" role="note">
        <strong>Synthetic evidence ({data.version}).</strong> Same generator, features and detectors as the canonical
        test, on a larger independently seeded population. Honest agents have zero fee noise in the simulator,
        so moderate skimming is an easy task here. Not field validation. The candidate scorer is not deployed.
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="panel"><div className="panel-body gap-1 p-4"><span className="muted">Final held-out agents</span><span className="text-2xl font-bold">{h.agents.toLocaleString()}</span><span className="muted">scored once, {data.replications} independent replications</span></div></div>
        <div className="panel"><div className="panel-body gap-1 p-4"><span className="muted">Skimmers / honest</span><span className="text-2xl font-bold">{h.skimmers} / {h.honest_agents.toLocaleString()}</span><span className="muted">{h.honest_high_volume} honest high-volume</span></div></div>
        <div className="panel"><div className="panel-body gap-1 p-4"><span className="muted">Subtle skimming found</span><span className="text-2xl font-bold text-error">{rate(subtleRecall)}</span><span className="muted">deployed ensemble, fixed 0.8 threshold</span></div></div>
        <div className="panel"><div className="panel-body gap-1 p-4"><span className="muted">Generated in total</span><span className="text-2xl font-bold">{data.agents_generated_total.toLocaleString()}</span><span className="muted">includes train and validation cohorts: not the held-out denominator</span></div></div>
      </div>
      <div className="overflow-x-auto rounded-box border border-base-300 bg-base-100" tabIndex={0} aria-label="Extended benchmark table, scrolls sideways">
        <table className="table table-sm">
          <caption className="px-4 py-2 text-left text-xs text-base-content/70">
            Recall at the fixed 0.8 risk threshold, 95% Wilson interval, and honest high-volume false flags. Scroll sideways on a phone.
          </caption>
          <thead>
            <tr><th>Scenario (final cohorts)</th><th>Skimmers</th>{SHOW.map((m) => <th key={m}>{data.scenarios[0].methods[m].label}</th>)}<th>Honest HV false flags (deployed)</th></tr>
          </thead>
          <tbody>
            {data.scenarios.map((s) => (
              <tr key={s.scenario} className={['subtle', 'unchanged_fee_shortfall_subtle', 'unchanged_fee_shortfall_moderate'].includes(s.scenario) ? 'bg-error/5' : ''}>
                <td className="font-mono text-xs">{s.scenario}</td>
                <td>{s.skimmers}</td>
                {SHOW.map((m) => <td key={m} className={s.methods[m].recall.rate === 0 ? 'font-semibold text-error' : ''}>{rate(s.methods[m].recall)}{ci(s.methods[m].recall)}</td>)}
                <td>{rate(s.methods.ensemble_v1.honest_high_volume_false_flags)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="list-disc pl-5 text-sm">
        <li><strong>Unchanged-fee cash shortfalls</strong> (correct fee, short payout): the deployed ensemble flags none. The development-selected candidate flags most moderate ones but is not deployed, and subtle shortfalls stay undetected by every method.</li>
        <li>Precision at a 5% review budget is capped at 66.7% (40 skimmers in 60 review slots per cohort). Threshold recall and precision-at-K are different policies.</li>
        <li>{data.canonical_comparison} Those canonical tables are unchanged.</li>
        <li className="muted text-xs">Protocol {data.protocol_sha256.slice(0, 12)}… · final results {data.final_results_sha256.slice(0, 12)}… · archive hashes re-verified on load.</li>
      </ul>
    </div>
  );
}

export default function ExtendedBenchmarkTab() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    api.getAgentBenchmarkV2().then((d) => { if (live) setData(d); }).catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, []);
  if (error) return <div role="alert" className="alert alert-warning alert-soft text-sm">Extended benchmark unavailable: {error}</div>;
  if (!data) return <span className="loading loading-dots loading-sm" aria-busy="true" />;
  return <ExtendedBenchmarkView data={data} />;
}
