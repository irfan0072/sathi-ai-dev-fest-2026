export default function NavTabs({ activeTab, onSelectTab }) {
  const tabs = [
    { id: 'simulation', label: '1. Live Mandate Simulator', icon: '⚡' },
    { id: 'cases', label: '2. Review Queue & Cases', icon: '🛡️' },
    { id: 'outreach', label: '3. Assisted User Outreach', icon: '👥' },
    { id: 'agents', label: '4. Agent Risk Board', icon: '🔍' },
    { id: 'metrics', label: '5. Evidence & Metrics', icon: '📊' },
    { id: 'architecture', label: '6. Problem & Principles', icon: '💡' },
  ];

  return (
    <nav className="nav-tabs" aria-label="Sathi Console Navigation">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
          onClick={() => onSelectTab(tab.id)}
          aria-current={activeTab === tab.id ? 'page' : undefined}
        >
          <span>{tab.icon}</span>
          <span>{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}
