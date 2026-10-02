import { useState, useCallback } from 'react';
import './style.css';
import Header from './components/Header';
import NavTabs from './components/NavTabs';
import LiveSimulation from './components/LiveSimulation';
import ReviewQueue from './components/ReviewQueue';
import OutreachList from './components/OutreachList';
import AgentRiskBoard from './components/AgentRiskBoard';
import MetricsPage from './components/MetricsPage';
import ArchitecturePage from './components/ArchitecturePage';

export default function App() {
  const [activeTab, setActiveTab] = useState('simulation');
  const [caseNotification, setCaseNotification] = useState(false);

  const handleCaseCreated = useCallback(() => {
    setCaseNotification(true);
    // Reset badge after a while
    setTimeout(() => setCaseNotification(false), 15000);
  }, []);

  const handleTabSelect = (tab) => {
    setActiveTab(tab);
    if (tab === 'cases') setCaseNotification(false);
  };

  const renderContent = () => {
    switch (activeTab) {
      case 'simulation':
        return <LiveSimulation onCaseCreated={handleCaseCreated} />;
      case 'cases':
        return <ReviewQueue />;
      case 'outreach':
        return <OutreachList />;
      case 'agents':
        return <AgentRiskBoard />;
      case 'metrics':
        return <MetricsPage />;
      case 'architecture':
        return <ArchitecturePage />;
      default:
        return <LiveSimulation onCaseCreated={handleCaseCreated} />;
    }
  };

  return (
    <>
      <Header />
      <NavTabs
        activeTab={activeTab}
        onSelectTab={handleTabSelect}
        caseNotification={caseNotification}
      />
      <main className="main-content">
        {renderContent()}
      </main>
    </>
  );
}
