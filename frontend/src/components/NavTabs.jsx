import Icon from './Icon';
import ThemeToggle from './ThemeToggle';

export const tabs = [
  { id: 'command', label: 'Dashboard', icon: 'chart', group: 'Daily work', title: 'Today at a glance', roles: ['analyst'] },
  { id: 'cashout', label: 'Cash-out', icon: 'flow', group: 'Daily work', title: 'Cash-out', roles: ['agent'] },
  { id: 'account', label: 'My account', icon: 'phone', group: 'Daily work', title: 'My account', roles: ['customer_channel'] },
  { id: 'transactions', label: 'Transactions', icon: 'receipt', group: 'Daily work', title: 'Cash-outs confirmed by customers', roles: ['analyst'] },
  { id: 'cases', label: 'Cases to review', icon: 'cases', group: 'Daily work', title: 'Cases to review', roles: ['analyst'] },
  { id: 'liquidity', label: 'Cash planning', icon: 'store', group: 'Agents', title: 'How much cash agents will need', roles: ['agent', 'analyst'] },
  { id: 'agents', label: 'Agent check', icon: 'radar', group: 'Agents', title: 'Agents with unusual activity', roles: ['analyst'] },
  { id: 'outreach', label: 'Customers who need help', icon: 'users', group: 'Customers', title: 'Customers who may need help', roles: ['analyst'] },
  { id: 'campaign', label: 'Invite planner', icon: 'users', group: 'Customers', title: 'Who to invite to Sathi', roles: ['analyst'] },
  { id: 'metrics', label: 'AI test results', icon: 'chart', group: 'Reports', title: 'How well the AI works', roles: ['analyst'] },
  { id: 'settings', label: 'Settings', icon: 'settings', group: 'System', title: 'Settings', roles: ['analyst'] },
  { id: 'architecture', label: 'How it works', icon: 'info', group: 'Help', title: 'How Sathi keeps cash-outs safe' },
];

export const canOpen = (tab, session) => !tab.roles || tab.roles.includes(session?.role);

export default function NavTabs({ activeTab, onSelectTab, session = null }) {
  // Locked tabs are hidden, not dimmed. This prevents role-leakage in the sidebar.
  const visibleTabs = tabs.filter((tab) => canOpen(tab, session));
  const groups = [...new Set(visibleTabs.map((tab) => tab.group))];

  return (
    <aside className="flex min-h-full w-72 flex-col border-r border-base-300 bg-base-100">
      <div className="flex items-center gap-3 border-b border-base-300 px-5 py-5">
        <span className="grid size-10 place-items-center rounded-xl bg-primary font-bangla text-lg font-bold text-primary-content">
          সাথী
        </span>
        <div className="leading-tight">
          <div className="text-lg font-extrabold tracking-wide">SATHI</div>
          <div className="text-xs text-base-content/60">Safe cash-out, no PIN sharing</div>
        </div>
      </div>

      <nav aria-label="Sathi Console Navigation" className="flex-1 overflow-y-auto px-3 py-4">
        {groups.map((group) => (
          <ul key={group} className="menu w-full gap-0.5 p-0 pb-5">
            <li className="menu-title px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-base-content/60">
              {group}
            </li>
            {visibleTabs
              .filter((tab) => tab.group === group)
              .map((tab) => {
                const selected = activeTab === tab.id;
                return (
                  <li key={tab.id}>
                    <button
                      className={`group gap-3 rounded-lg py-2.5 pl-3 pr-2 transition focus-ring ${
                        selected ? 'menu-active font-medium' : 'hover:bg-base-200/70'
                      }`}
                      onClick={() => onSelectTab(tab.id)}
                      aria-current={selected ? 'page' : undefined}
                    >
                      <Icon name={tab.icon} className="size-4 shrink-0" />
                      <span className="flex-1 text-left text-sm">{tab.label}</span>
                    </button>
                  </li>
                );
              })}
          </ul>
        ))}
      </nav>

      <div className="m-3 mt-2 flex items-center justify-between gap-2 rounded-box border border-base-300 bg-base-200/60 p-3 text-[11px] leading-relaxed text-base-content/80">
        <span className="flex-1">
          Demo version with made-up data. Not connected to real upay accounts.
        </span>
        <ThemeToggle />
      </div>
    </aside>
  );
}