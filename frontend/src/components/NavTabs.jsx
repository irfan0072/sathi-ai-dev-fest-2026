import Icon from './Icon';

export const tabs = [
  { id: 'command', label: 'Command Center', icon: 'chart', group: 'Operations', title: 'Fraud command center', roles: ['analyst'] },
  { id: 'simulation', label: 'Live Mandate Simulator', icon: 'flow', group: 'Operations', title: 'Cash-out mandate flow' },
  { id: 'cases', label: 'Review Queue', icon: 'cases', group: 'Operations', title: 'Supervisor review queue', roles: ['analyst'] },
  { id: 'liquidity', label: 'Liquidity Forecast', icon: 'store', group: 'Ecosystem', title: 'Agent liquidity forecast', roles: ['agent', 'analyst'] },
  { id: 'campaign', label: 'Adoption Uplift', icon: 'users', group: 'Ecosystem', title: 'Sathi adoption campaign', roles: ['analyst'] },
  { id: 'agents', label: 'Agent Risk Board', icon: 'radar', group: 'Ecosystem', title: 'Agent anomaly risk', roles: ['analyst'] },
  { id: 'outreach', label: 'Assisted User Outreach', icon: 'users', group: 'Evidence', title: 'Assisted user outreach', roles: ['analyst'] },
  { id: 'metrics', label: 'Evidence & Metrics', icon: 'chart', group: 'Evidence', title: 'Synthetic evidence and metrics', roles: ['analyst'] },
  { id: 'architecture', label: 'How Sathi Works', icon: 'info', group: 'About', title: 'Problem, solution and principles' },
];

export const canOpen = (tab, session) => !tab.roles || tab.roles.includes(session?.role);

export default function NavTabs({ activeTab, onSelectTab, session = null }) {
  const groups = [...new Set(tabs.map((tab) => tab.group))];
  return (
    <aside className="flex min-h-full w-72 flex-col border-r border-base-300 bg-base-100">
      <div className="flex items-center gap-3 px-5 py-5">
        <span className="grid size-10 place-items-center rounded-xl bg-primary font-bangla text-lg font-bold text-primary-content">সাথী</span>
        <div className="leading-tight">
          <div className="text-lg font-extrabold tracking-wide">SATHI</div>
          <div className="text-xs opacity-60">Scoped cash-out mandates</div>
        </div>
      </div>

      <nav aria-label="Sathi Console Navigation" className="flex-1 px-3">
        {groups.map((group) => (
          <ul key={group} className="menu w-full gap-0.5 p-0 pb-4">
            <li className="menu-title px-3 text-[11px] uppercase tracking-wider">{group}</li>
            {tabs.filter((tab) => tab.group === group).map((tab) => {
              const locked = !canOpen(tab, session);
              return (
                <li key={tab.id}>
                  <button
                    className={`gap-3 py-2.5 ${activeTab === tab.id ? 'menu-active' : ''}`}
                    onClick={() => onSelectTab(tab.id)}
                    aria-current={activeTab === tab.id ? 'page' : undefined}
                  >
                    <Icon name={tab.icon} />
                    <span className="flex-1 text-left">{tab.label}</span>
                    {locked && <Icon name="lock" className="size-3.5 opacity-40" />}
                  </button>
                </li>
              );
            })}
          </ul>
        ))}
      </nav>

      <div className="m-3 rounded-box bg-base-200 p-3 text-[11px] leading-relaxed opacity-80">
        Track 07 · AI DEV FEST 2026 · DIU CPC × upay. Research prototype on synthetic data; not connected to upay production.
      </div>
    </aside>
  );
}
