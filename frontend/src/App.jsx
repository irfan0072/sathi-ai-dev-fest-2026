import { Suspense, lazy, useState, useEffect } from 'react';
import './style.css';
import { api } from './api';
import Header from './components/Header';
import DemoLogin from './components/DemoLogin';
import LoginScreen, { landingTabForRole } from './components/LoginScreen';
import NavTabs, { canOpen, findTab } from './components/NavTabs';
import Icon from './components/Icon';
import ErrorBoundary from './components/ErrorBoundary';
// Pages load on first visit, so the sign-in screen only downloads what it needs.
const page = (loader, name = 'default') => lazy(() => loader().then((m) => ({ default: m[name] })));
const AgentCashout = page(() => import('./components/AgentCashout'));
const CustomerAccount = page(() => import('./components/CustomerAccount'));
const TransactionsPage = page(() => import('./components/TransactionsPage'));
const ReviewQueue = page(() => import('./components/ReviewQueue'));
const OutreachList = page(() => import('./components/OutreachList'));
const AgentRiskBoard = page(() => import('./components/AgentRiskBoard'));
const MetricsPage = page(() => import('./components/MetricsPage'));
const ArchitecturePage = page(() => import('./components/ArchitecturePage'));
const LiquidityPage = page(() => import('./components/LiquidityPage'));
const UpliftPage = page(() => import('./components/UpliftPage'));
const CommandCenter = page(() => import('./components/CommandCenter'));
const SettingsPage = page(() => import('./components/SettingsPage'));
const AdminDashboard = page(() => import('./components/ops/AdminDashboard'));
const WorkflowEvidence = page(() => import('./components/ops/WorkflowEvidence'));
const CallCenter = page(() => import('./components/ops/CallCenter'));
const CaseWorkbench = page(() => import('./components/ops/CaseWorkbench'));
const scam = () => import('./components/ScamProtection');
const CommunityPage = page(scam, 'CommunityPage');
const ScamWatch = page(scam, 'ScamWatch');
const SendMoney = page(scam, 'SendMoney');
const dirs = () => import('./components/ops/Directories');
const AgentsDirectory = page(dirs, 'AgentsDirectory');
const AuditLogPage = page(dirs, 'AuditLogPage');
const LedgerPage = page(dirs, 'LedgerPage');
const StaffPage = page(dirs, 'StaffPage');
const SupervisorDesk = page(dirs, 'SupervisorDesk');
const UsersPage = page(dirs, 'UsersPage');
const TestAccounts = page(() => import('./components/ops/TestAccounts'));

const PageLoading = () => (
  <div className="flex justify-center py-16" aria-busy="true">
    <span className="loading loading-spinner loading-md text-primary" />
  </div>
);

const TAB_KEY = 'sathi_tab';
const savedTab = (session) => {
  if (!session) return 'architecture';
  try {
    const id = window.sessionStorage.getItem(TAB_KEY);
    if (canOpen(findTab(id, session), session)) return id;
  } catch { /* storage unavailable */ }
  return landingTabForRole(session.role);
};
const rememberTab = (id) => {
  try { window.sessionStorage.setItem(TAB_KEY, id); } catch { /* storage unavailable */ }
};

export default function App() {
  const [session, setSession] = useState(api.getSession);
  const [activeTab, setActiveTab] = useState(() => savedTab(api.getSession()));
  const [focusCase, setFocusCase] = useState(null);
  const [login, setLogin] = useState(null); // { role, nonce } for "Switch role" modal

  useEffect(() => {
    return api.subscribeSession((next) => {
      setSession(next);
      if (next?.role) {
        // Land each role on its own home page on sign-in.
        setActiveTab(landingTabForRole(next.role));
        rememberTab(landingTabForRole(next.role));
      } else {
        // Signed out — reset to a safe default so the next sign-in can reroute.
        setActiveTab('architecture');
      }
    });
  }, []);

  const openLogin = (role = session?.role || 'agent') => setLogin({ role, nonce: Date.now() });
  const closeLogin = () => setLogin(null);

  const selectTab = (id) => {
    if (!canOpen(findTab(id, session), session)) return;
    setActiveTab(id);
    rememberTab(id);
    if (typeof document !== 'undefined') {
      const toggle = document.getElementById('sathi-drawer');
      if (toggle) toggle.checked = false;
    }
  };

  // ── Unauthenticated: render only the login screen, nothing else. ──
  if (!session) {
    return (
      <>
        <LoginScreen onSuccess={closeLogin} />
        {login && (
          <div
            className="modal modal-open modal-bottom sm:modal-middle"
            role="dialog"
            aria-modal="true"
            aria-label="Demo sign in"
          >
            <div className="modal-box max-w-2xl">
              <button
                className="btn btn-ghost btn-sm btn-circle absolute right-3 top-3 focus-ring"
                onClick={closeLogin}
                aria-label="Close"
              >
                <Icon name="x" className="size-4" />
              </button>
              <h3 className="mb-1 text-lg font-bold">Sign in</h3>
              <p className="mb-4 text-sm text-base-content/70">
                Choose who you are.
              </p>
              <DemoLogin key={login.nonce} session={null} initialRole={login.role} onDone={closeLogin} />
            </div>
            <button className="modal-backdrop" onClick={closeLogin} aria-label="Close dialog" />
          </div>
        )}
      </>
    );
  }

  // ── Authenticated: render the role-scoped dashboard. ──
  const tab = findTab(activeTab, session);
  // Defensive: if a user types a tab they can't open (e.g. via stale URL),
  // fall back to their landing tab rather than rendering AnalystGate.
  const effectiveTab = tab && canOpen(tab, session) ? tab : findTab(landingTabForRole(session.role), session);
  const showTab = effectiveTab || tab;

  const caseTab = session.role === 'analyst' ? 'cases' : 'casework';
  const content = () => {
    const id = showTab?.id;
    if (id === 'architecture') return <ArchitecturePage />;
    if (id === 'cashout') return <AgentCashout session={session} />;
    if (id === 'account') return <CustomerAccount />;
    if (id === 'transactions') return <TransactionsPage onOpenCases={(caseId) => { setFocusCase(caseId || null); selectTab(caseTab); }} />;
    if (id === 'command') return <CommandCenter onOpenCases={() => selectTab(caseTab)} onOpenTransactions={() => selectTab('transactions')} />;
    if (id === 'liquidity') return <LiquidityPage session={session} />;
    if (id === 'campaign') return <UpliftPage />;
    if (id === 'cases') return <ReviewQueue initialCaseId={focusCase} session={session} />;
    if (id === 'outreach') return <OutreachList />;
    if (id === 'agents') return <AgentRiskBoard />;
    if (id === 'metrics') return <MetricsPage />;
    if (id === 'settings') return <SettingsPage />;
    if (id === 'evidence') return <WorkflowEvidence />;
    if (id === 'admin') return <AdminDashboard onOpen={selectTab} />;
    if (id === 'desk') return <SupervisorDesk session={session} onOpen={selectTab} />;
    if (id === 'callcenter') return <CallCenter session={session} />;
    if (id === 'casework') return <CaseWorkbench session={session} initialCaseId={focusCase} />;
    if (id === 'ledger') return <LedgerPage />;
    if (id === 'send') return <SendMoney />;
    if (id === 'community') return <CommunityPage />;
    if (id === 'scamwatch') return <ScamWatch session={session} />;
    if (id === 'users') return <UsersPage />;
    if (id === 'agents-dir') return <AgentsDirectory />;
    if (id === 'staff') return <StaffPage />;
    if (id === 'accounts') return <TestAccounts />;
    if (id === 'auditlog') return <AuditLogPage />;
    // Fallback: render a small empty state if nothing matches.
    return (
      <div className="panel mx-auto max-w-md text-center shadow-sm">
        <div className="panel-body items-center gap-3">
          <Icon name="info" className="size-6 text-base-content/50" />
          <h2 className="text-lg font-semibold">Nothing to show here</h2>
          <p className="text-sm text-base-content/70">Choose a page from the menu.</p>
        </div>
      </div>
    );
  };

  return (
    <div className="drawer lg:drawer-open bg-base-200">
      <input id="sathi-drawer" type="checkbox" className="drawer-toggle" />
      <div className="drawer-content flex min-h-screen flex-col">
        <Header
          title={showTab?.title}
          session={session}
          onLogin={openLogin}
          onLogout={() => api.logout()}
        />
        <div
          className="border-b border-warning/40 bg-warning/15 px-4 py-2 text-center text-[11px] font-medium text-warning-content sm:text-xs"
          role="region"
          aria-label="Demo warning"
        >
          Hackathon concept for upay, not endorsed by upay. Live system on synthetic customers
          (no real upay accounts). Fixed rules detect; the AI ranks cases for review; a person
          makes every decision.
        </div>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-5 sm:px-6 sm:py-6 lg:py-8">
          <div
            key={`${session?.role}:${session?.subject}:${showTab?.id}`}
            className="animate-fadeIn"
          >
            <ErrorBoundary key={showTab?.id}><Suspense fallback={<PageLoading />}>{content()}</Suspense></ErrorBoundary>
          </div>
        </main>
        <footer className="border-t border-base-300 bg-base-100 px-4 py-3 text-center text-xs text-base-content/60 sm:px-6">
          Sathi · AI DEV FEST 2026 · DIU CPC × upay
        </footer>
      </div>
      <div className="drawer-side z-40">
        <label htmlFor="sathi-drawer" aria-label="Close navigation" className="drawer-overlay" />
        <NavTabs activeTab={showTab?.id} onSelectTab={(id) => { setFocusCase(null); selectTab(id); }} session={session} />
      </div>

      {login && (
        <div
          className="modal modal-open modal-bottom sm:modal-middle"
          role="dialog"
          aria-modal="true"
          aria-label="Switch demo role"
        >
          <div className="modal-box max-w-2xl">
            <button
              className="btn btn-ghost btn-sm btn-circle absolute right-3 top-3 focus-ring"
              onClick={closeLogin}
              aria-label="Close"
            >
              <Icon name="x" className="size-4" />
            </button>
            <h3 className="mb-1 text-lg font-bold">Switch user</h3>
            <p className="mb-4 text-sm text-base-content/70">
              Act as someone else. Your current cash-out stays open.
            </p>
            <DemoLogin key={login.nonce} session={session} initialRole={login.role} onDone={closeLogin} />
          </div>
          <button className="modal-backdrop" onClick={closeLogin} aria-label="Close dialog" />
        </div>
      )}
    </div>
  );
}