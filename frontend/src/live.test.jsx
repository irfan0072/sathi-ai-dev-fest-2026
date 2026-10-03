import { describe, it, expect } from 'vitest';
import { renderToString } from 'react-dom/server';
import LiveSimulation from './components/LiveSimulation';
import { RiskCard } from './components/LiveCall';
import { BriefView } from './components/CaseBrief';
import { ForecastChart, QiniChart } from './components/Charts';
import { AgentForecast } from './components/LiquidityPage';
import App from './App';

const clean = (html) => html.replace(/<!-- -->/g, '');

describe('Live verification channel', () => {
  it('agent sees the call action but never the customer amount controls', () => {
    const html = clean(renderToString(<LiveSimulation session={{ role: 'agent', subject: 'A_1', allowed_users: ['U_1'] }} flow={{ mandateId: 'm1', status: 'requested' }} />));
    expect(html).toContain('Call customer to confirm');
    expect(html).toContain('registered');
    expect(html).not.toContain('Confirm amount');
  });

  it('customer can choose phone call or in-app confirmation', () => {
    const html = renderToString(<LiveSimulation session={{ role: 'customer_channel', subject: 'U_1' }} flow={{ mandateId: 'm1' }} />);
    expect(html).toContain('Phone call');
    expect(html).toContain('In app');
    expect(html).not.toContain('Call customer to confirm');
  });

  it('risk card states that risk never authorizes', () => {
    const html = clean(renderToString(<RiskCard risk={{ score: 0.72, band: 'high', step_up: 'call_and_review', reasons: [{ signal: 'x', explanation: 'Agent has 3 cases.' }] }} />));
    expect(html).toContain('high');
    expect(html).toContain('Phone call required + analyst review case opened');
    expect(html).toContain('never approves or denies');
    expect(html).not.toContain('Agent has 3 cases.');
  });
});

describe('AI case brief', () => {
  it('renders grounded brief with escaped text and provider label', () => {
    const html = clean(renderToString(<BriefView result={{
      provider: 'gemini', model: 'gemini-2.5-flash', fallbacks: [],
      facts: [{ id: 'F1', field: 'case.reason', value: 'duress_signal' }],
      brief: {
        headline: '<script>alert(1)</script>', what_happened: 'w',
        why_risky: [{ point: 'p', evidence: ['F1'] }], recommended_next_step_text: 'Call the customer.',
        questions_for_customer: ['q?'], summary_bn: 'বাংলা',
      },
    }} />));
    expect(html).toContain('Gemini');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>');
    expect(html).toContain('case.reason: duress_signal');
    expect(html).toContain('It is not a decision');
  });
});

describe('Ecosystem intelligence views', () => {
  const days = Array.from({ length: 7 }, (_, i) => ({ date: `2026-12-0${i + 1}`, forecast_bdt: 1000 + i * 100, p90_bdt: 2000 + i * 100 }));

  it('forecast chart labels both marks', () => {
    const html = renderToString(<ForecastChart days={days} />);
    expect(html).toContain('Expected demand');
    expect(html).toContain('P90 (busy-day) demand');
  });

  it('agent forecast shows float recommendation and planning-only boundary', () => {
    const html = clean(renderToString(<AgentForecast data={{ agent_id: 'A_1', days, recommended_opening_float_bdt: 3000, peak_p90_bdt: 2600, peak_date: '2026-12-07', typical_daily_bdt: 1200, pressure_ratio: 2.1, max_daily_35d_bdt: 2000, exceeds_recent_max: true, basis: 'own synthetic history', forecast_origin: '2026-12-01' }} />));
    expect(html).toContain('৳3,000');
    expect(html).toContain('never limits');
  });

  it('qini chart has a legend and direct labels for every policy', () => {
    const curve = [0, 0.5, 1].map((s) => ({ targeted_share: s, incremental: s * 10 }));
    const html = renderToString(<QiniChart policies={{ uplift_t_learner: { curve }, response_model: { curve }, random: { curve } }} />);
    expect(html.match(/Uplift model/g).length).toBeGreaterThanOrEqual(2);
    expect(html).toContain('Random');
  });

  it('navigation lists the new pages', () => {
    const html = renderToString(<App />);
    expect(html).toContain('Liquidity Forecast');
    expect(html).toContain('Adoption Uplift');
  });
});
