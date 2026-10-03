import { describe, it, expect } from 'vitest';
import { renderToString } from 'react-dom/server';
import CommandCenter, { WatchButton } from './components/CommandCenter';
import ReviewQueue from './components/ReviewQueue';
import { StateBar } from './components/Charts';
import { SmsInbox } from './components/LiveCall';
import App from './App';

const clean = (html) => html.replace(/<!-- -->/g, '');

describe('Fraud operations UI', () => {
  it('command center starts in a loading state without invented numbers', () => {
    const html = renderToString(<CommandCenter />);
    expect(html).toContain('Fraud Command Center');
    expect(html).toContain('Loading live operations');
    expect(html).not.toContain('৳');
  });

  it('review queue offers priority filters', () => {
    const html = renderToString(<ReviewQueue />);
    for (const label of ['Open', 'Urgent', 'Past target', 'All']) expect(html).toContain(label);
  });

  it('watch button explains its effect', () => {
    expect(renderToString(<WatchButton agentId="A_1" watchlisted={false} />)).toContain('Require a verification call');
    expect(renderToString(<WatchButton agentId="A_1" watchlisted />)).toContain('Watchlisted');
  });

  it('state bar always labels each state with its count', () => {
    const html = clean(renderToString(<StateBar parts={[{ label: 'Low', value: 3, color: 'red' }, { label: 'High', value: 1, color: 'blue' }]} />));
    expect(html).toContain('Low <strong>3</strong>');
    expect(renderToString(<StateBar parts={[{ label: 'Low', value: 0, color: 'red' }]} />)).toContain('No data');
  });

  it('sms inbox explains when receipts arrive', () => {
    expect(renderToString(<SmsInbox />)).toContain('receipt SMS arrives after every cash-out');
  });

  it('navigation lists the command center', () => {
    expect(renderToString(<App />)).toContain('Command Center');
  });
});
