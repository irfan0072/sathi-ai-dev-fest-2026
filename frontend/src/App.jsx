import { useState, useEffect } from 'react';
import './style.css';
import { api } from './api';
import Header from './components/Header';
import DemoLogin from './components/DemoLogin';
import NavTabs, { canOpen, tabs } from './components/NavTabs';
import Icon from './components/Icon';
import LiveSimulation from './components/LiveSimulation';
import ReviewQueue from './components/ReviewQueue';
import OutreachList from './components/OutreachList';
import AgentRiskBoard from './components/AgentRiskBoard';
import MetricsPage from './components/MetricsPage';
import ArchitecturePage from './components/ArchitecturePage';
import LiquidityPage from './components/LiquidityPage';
import UpliftPage from './components/UpliftPage';
import CommandCenter from './components/CommandCenter';

function AnalystGate({ roles = ['analyst'], onSignIn }) {
  const agentToo = roles.includes('agent');
  return (
    <div className="panel mx-auto max-w-md text-center">
      <div className="panel-body items-center">
        <span className="grid size-12 place-items-center rounded-full bg-accent/20"><Icon name="lock" className="size-6" /></span>
        <h2 className="text-lg font-semibold">{agentToo ? 'Agent or analyst access' : 'Analyst access only'}</h2>
        <p className="text-sm opacity-70">{agentToo ? 'Sign in as an agent to see your own forecast, or as the analyst to see every agent.' : 'Sign in as the human analyst to view saved evidence and review cases.'}</p>
        <button className="btn btn-primary btn-sm" onClick={onSignIn}>Sign in as analyst</button>
      </div>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState('simulation');
  const [session, setSession] = useState(api.getSession);
  const [flow, setFlow] = useState({});
  const [login, setLogin] = useState(null); // { role, nonce } while the sign-in dialog is open
  useEffect(() => api.subscribeSession((next) => {
    setSession(next);
    // Analysts land on the command center; other roles keep their current page.
    if (next?.role === 'analyst') setActiveTab((tab) => (tab === 'simulation' ? 'command' : tab));
  }), []);

  const openLogin = (role = session?.role || 'agent') => setLogin({ role, nonce: Date.now() });
  const closeLogin = () => setLogin(null);
  const selectTab = (id) => {
    setActiveTab(id);
    if (typeof document !== 'undefined') {
      const toggle = document.getElementById('sathi-drawer');
      if (toggle) toggle.checked = false;
    }
  };

  const tab = tabs.find((item) => item.id === activeTab);
  const content = () => {
    if (activeTab === 'architecture') return <ArchitecturePage />;
    if (activeTab === 'simulation') return <LiveSimulation session={session} flow={flow} setFlow={setFlow} onSwitchRole={openLogin} />;
    if (!canOpen(tab, session)) return <AnalystGate roles={tab.roles} onSignIn={() => openLogin(tab.roles[tab.roles.length - 1])} />;
    if (activeTab === 'command') return <CommandCenter onOpenCases={() => setActiveTab('cases')} />;
    if (activeTab === 'liquidity') return <LiquidityPage session={session} />;
    if (activeTab === 'campaign') return <UpliftPage />;
    if (activeTab === 'cases') return <ReviewQueue />;
    if (activeTab === 'outreach') return <OutreachList />;
    if (activeTab === 'agents') return <AgentRiskBoard />;
    return <MetricsPage />;
  };

  return (
    <div className="drawer lg:drawer-open">
      <input id="sathi-drawer" type="checkbox" className="drawer-toggle" />
      <div className="drawer-content flex min-h-screen flex-col">
        <Header title={tab?.title} session={session} onLogin={openLogin}
          onLogout={() => { api.logout(); setFlow({}); }} />
        <div className="border-b border-warning/40 bg-warning/15 px-4 py-1.5 text-center text-[11px] font-medium sm:text-xs">
          SYNTHETIC DEMO · No real upay data or transactions. All financial figures are ASSUMPTIONS. Models never authorize cash-out.
        </div>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6">
          <div key={`${session?.role || 'signed-out'}:${session?.subject || ''}`}>{content()}</div>
        </main>
      </div>
      <div className="drawer-side z-40">
        <label htmlFor="sathi-drawer" aria-label="Close navigation" className="drawer-overlay" />
        <NavTabs activeTab={activeTab} onSelectTab={selectTab} session={session} />
      </div>

      {login && (
        <div className="modal modal-open modal-bottom sm:modal-middle" role="dialog" aria-modal="true" aria-label="Demo sign in">
          <div className="modal-box max-w-2xl">
            <button className="btn btn-ghost btn-sm btn-circle absolute right-3 top-3" onClick={closeLogin} aria-label="Close"><Icon name="x" className="size-4" /></button>
            <h3 className="mb-1 text-lg font-bold">{session ? 'Switch demo role' : 'Sign in to the synthetic demo'}</h3>
            <p className="mb-4 text-sm opacity-70">Each role is a separate channel. The mandate in progress stays loaded when you switch.</p>
            <DemoLogin key={login.nonce} session={session} initialRole={login.role} onDone={closeLogin} />
          </div>
          <button className="modal-backdrop" onClick={closeLogin} aria-label="Close dialog" />
        </div>
      )}
    </div>
  );
}
