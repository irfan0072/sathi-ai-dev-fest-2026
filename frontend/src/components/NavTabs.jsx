import Icon from './Icon';
import ThemeToggle from './ThemeToggle';

export const tabs = [
  // Super admin
  { id: 'admin', label: 'Control center', icon: 'chart', group: 'Overview', title: 'Control center', roles: ['super_admin'] },
  { id: 'callcenter', label: 'Call management', icon: 'phone', group: 'Operations', title: 'Call management', roles: ['super_admin'] },
  { id: 'casework', label: 'Cases', icon: 'cases', group: 'Operations', title: 'Cases', roles: ['super_admin'] },
  { id: 'ledger', label: 'All transactions', icon: 'receipt', group: 'Operations', title: 'All transactions', roles: ['super_admin'] },
  { id: 'scamwatch', label: 'Scam watch', icon: 'warning', group: 'Operations', title: 'Scam watch', roles: ['super_admin'] },
  { id: 'users', label: 'Customers', icon: 'users', group: 'Directory', title: 'Customers', roles: ['super_admin'] },
  { id: 'agents-dir', label: 'Agents', icon: 'store', group: 'Directory', title: 'Agents', roles: ['super_admin'] },
  { id: 'staff', label: 'Supervisors', icon: 'shield', group: 'Directory', title: 'Supervisors and admins', roles: ['super_admin'] },
  // Supervisor
  { id: 'desk', label: 'My desk', icon: 'chart', group: 'My work', title: 'My desk', roles: ['supervisor'] },
  { id: 'callcenter', label: 'Call queue', icon: 'phone', group: 'My work', title: 'Call queue', roles: ['supervisor'] },
  { id: 'casework', label: 'Cases', icon: 'cases', group: 'My work', title: 'Cases to review', roles: ['supervisor'] },
  { id: 'scamwatch', label: 'Scam watch', icon: 'warning', group: 'My work', title: 'Scam watch', roles: ['supervisor'] },
  // Fraud analytics (analyst and super admin)
  { id: 'command', label: 'Fraud dashboard', icon: 'radar', group: 'Analytics', title: 'Fraud dashboard', roles: ['analyst', 'super_admin'] },
  { id: 'transactions', label: 'Confirmations', icon: 'receipt', group: 'Analytics', title: 'Confirmations', roles: ['analyst', 'super_admin'] },
  { id: 'cases', label: 'Cases to review', icon: 'cases', group: 'Analytics', title: 'Cases to review', roles: ['analyst'] },
  { id: 'agents', label: 'Agent risk (AI)', icon: 'radar', group: 'Analytics', title: 'Agent risk (AI)', roles: ['analyst', 'super_admin'] },
  { id: 'liquidity', label: 'Cash planning', icon: 'store', group: 'Analytics', title: 'How much cash agents will need', roles: ['agent', 'analyst', 'super_admin'] },
  { id: 'outreach', label: 'Customers who need help', icon: 'users', group: 'Analytics', title: 'Customers who may need help', roles: ['analyst', 'super_admin'] },
  { id: 'campaign', label: 'Invite planner', icon: 'users', group: 'Analytics', title: 'Who to invite to Sathi', roles: ['analyst', 'super_admin'] },
  { id: 'metrics', label: 'AI test results', icon: 'chart', group: 'Analytics', title: 'How well the AI works', roles: ['analyst', 'super_admin'] },
  // Agent and customer
  { id: 'cashout', label: 'Cash-out', icon: 'flow', group: 'Daily work', title: 'Cash-out', roles: ['agent'] },
  { id: 'account', label: 'My account', icon: 'phone', group: 'Daily work', title: 'My account', roles: ['customer_channel'] },
  { id: 'send', label: 'Send money', icon: 'arrow', group: 'Daily work', title: 'Send money', roles: ['customer_channel'] },
  { id: 'community', label: 'Scam alerts', icon: 'shield', group: 'Daily work', title: 'Scam alerts', roles: ['customer_channel'] },
  // System
  { id: 'auditlog', label: 'Audit log', icon: 'lock', group: 'System', title: 'Audit log', roles: ['super_admin'] },
  { id: 'settings', label: 'Settings', icon: 'settings', group: 'System', title: 'Settings', roles: ['super_admin'] },
  { id: 'architecture', label: 'How it works', icon: 'info', group: 'Help', title: 'How Sathi keeps cash-outs safe' },
];

export const findTab = (id, session) => tabs.find((t) => t.id === id && canOpen(t, session)) || tabs.find((t) => t.id === id);

export const canOpen = (tab, session) => Boolean(tab) && (!tab.roles || tab.roles.includes(session?.role));

export default function NavTabs({ activeTab, onSelectTab, session = null }) {
  // Locked tabs are hidden, not dimmed. This prevents role-leakage in the sidebar.
  const visibleTabs = tabs.filter((tab) => canOpen(tab, session));
  const order = ['Overview', 'Daily work', 'My work', 'Operations', 'Directory', 'Analytics', 'System', 'Help'];
  const groups = [...new Set(visibleTabs.map((tab) => tab.group))]
    .sort((a, b) => order.indexOf(a) - order.indexOf(b));

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
                  <li key={`${tab.id}-${tab.group}`}>
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
          {session?.display_name ? <><strong>{session.display_name}</strong><br /></> : null}
          Synthetic data. Not connected to real upay accounts.
        </span>
        <ThemeToggle />
      </div>
    </aside>
  );
}