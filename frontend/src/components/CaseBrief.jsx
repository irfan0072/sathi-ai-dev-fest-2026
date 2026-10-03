import { useState } from 'react';
import { api } from '../api';
import Icon from './Icon';

const providerLabel = { gemini: 'Written by Gemini AI', openai: 'Written by GPT-4o AI', template: 'Standard summary' };

export function BriefView({ result }) {
  const facts = Object.fromEntries((result.facts || []).map((f) => [f.id, f]));
  const brief = result.brief;
  return (
    <div className="flex flex-col gap-3 rounded-box border border-secondary/30 bg-secondary/5 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge badge-secondary badge-sm">{providerLabel[result.provider] || result.provider}</span>
        {result.fallbacks?.length > 0 && <span className="muted">· first choice was not available</span>}
      </div>
      <h4 className="font-semibold">{brief.headline}</h4>
      <div>
        <div className="muted mb-0.5 uppercase tracking-wide">What happened</div>
        <p className="text-sm">{brief.what_happened}</p>
      </div>
      <div>
        <div className="muted mb-1 uppercase tracking-wide">Why it looks risky</div>
        <ul className="flex flex-col gap-1.5">
          {brief.why_risky.map((item) => (
            <li key={item.point} className="text-sm">
              {item.point}{' '}
              {item.evidence.map((id) => (
                <span key={id} className="tooltip" data-tip={facts[id] ? `${facts[id].field}: ${String(facts[id].value)}` : id}>
                  <span className="badge badge-ghost badge-xs">proof</span>
                </span>
              ))}
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-box bg-base-100 p-3">
        <div className="muted mb-0.5 uppercase tracking-wide">What to do next</div>
        <p className="text-sm font-medium">{brief.recommended_next_step_text}</p>
      </div>
      {brief.questions_for_customer?.length > 0 && (
        <div>
          <div className="muted mb-0.5 uppercase tracking-wide">Ask the customer</div>
          <ul className="list-inside list-disc text-sm">{brief.questions_for_customer.map((q) => <li key={q}>{q}</li>)}</ul>
        </div>
      )}
      <p lang="bn" className="text-sm">{brief.summary_bn}</p>
      <p className="muted">This summary uses only the facts of this case. It is not a decision — you decide.</p>
    </div>
  );
}

export default function CaseBrief({ caseId }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generate = async () => {
    setBusy(true); setError('');
    try { setResult(await api.generateCaseBrief(caseId)); } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return (
    <div className="flex flex-col gap-2">
      <button className="btn btn-secondary btn-sm btn-soft self-start" disabled={busy} onClick={generate}>
        {busy ? <span className="loading loading-spinner loading-xs" /> : <Icon name="info" className="size-4" />}
        {result ? 'Write the summary again' : 'Summarize this case with AI'}
      </button>
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}
      {result && <BriefView result={result} />}
    </div>
  );
}
