import { useState, useEffect } from 'react';
import './style.css';
import { api } from './api';
import Header from './components/Header';
import DemoLogin from './components/DemoLogin';
import NavTabs from './components/NavTabs';
import LiveSimulation from './components/LiveSimulation';
import ReviewQueue from './components/ReviewQueue';
import OutreachList from './components/OutreachList';
import AgentRiskBoard from './components/AgentRiskBoard';
import MetricsPage from './components/MetricsPage';
import ArchitecturePage from './components/ArchitecturePage';

export default function App() {
  const [activeTab, setActiveTab] = useState('simulation');
  const [session, setSession] = useState(api.getSession);
  const [flow, setFlow] = useState({});
  useEffect(() => api.subscribeSession(setSession), []);
  const content = () => {
    if (activeTab === 'architecture') return <ArchitecturePage />;
    if (activeTab === 'simulation') return <LiveSimulation session={session} flow={flow} setFlow={setFlow} />;
    if (session?.role !== 'analyst') return <div className="glass-card">Sign in as the human analyst to view saved evidence and review cases.</div>;
    if (activeTab === 'cases') return <ReviewQueue />;
    if (activeTab === 'outreach') return <OutreachList />;
    if (activeTab === 'agents') return <AgentRiskBoard />;
    return <MetricsPage />;
  };
  return <>
    <Header />
    <div className="synthetic-banner">SYNTHETIC DEMO · No real upay data or transactions. All financial figures are ASSUMPTIONS. Models never authorize cash-out.</div>
    <main className="main-content">
      <DemoLogin session={session} onLogout={() => { api.logout(); setFlow({}); }} />
      <NavTabs activeTab={activeTab} onSelectTab={setActiveTab} />
      <div key={`${session?.role || 'signed-out'}:${session?.subject || ''}`}>{content()}</div>
    </main>
  </>;
}
