import { useState, useEffect } from 'react';
import { API_BASE_URL, setApiBaseUrl, api } from '../api';
import Icon from './Icon';
import ThemeToggle from './ThemeToggle';
import { roleMeta } from './DemoLogin';
import { phone } from '../ids';

const health = {
  unknown: { color: '#94a3b8', label: 'Connecting…' }, // never green until verified
  healthy: { color: '#10b981', label: 'Online' },
  unhealthy: { color: '#f43f5e', label: 'Offline: server not reachable' },
};

export default function Header({ title = '', session = null, onLogin = () => {}, onLogout = () => {} }) {
  const [healthStatus, setHealthStatus] = useState('unknown');
  const [currentUrl, setCurrentUrl] = useState(API_BASE_URL);
  const [deployment, setDeployment] = useState(null);

  useEffect(() => {
    let mounted = true;
    api.getDeployment().then((d) => mounted && setDeployment(d)).catch(() => {});
    return () => { mounted = false; };
  }, [currentUrl]);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      const ok = await api.checkHealth();
      if (mounted) setHealthStatus(ok ? 'healthy' : 'unhealthy');
    };
    check();
    const interval = setInterval(check, 5000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [currentUrl]);

  const toggleEndpoint = () => {
    const nextUrl = currentUrl.includes(':18000') ? 'http://127.0.0.1:18001' : 'http://127.0.0.1:18000';
    if (setApiBaseUrl(nextUrl)) setCurrentUrl(nextUrl);
  };

  const status = health[healthStatus];
  const role = session ? roleMeta[session.role] : null;

  return (
    <header className="navbar sticky top-0 z-30 gap-3 border-b border-base-300 bg-base-100/95 px-4 py-2 backdrop-blur supports-[backdrop-filter]:bg-base-100/80 sm:px-6">
      <div className="flex flex-1 items-center gap-3 min-w-0">
        <label htmlFor="sathi-drawer" className="btn btn-ghost btn-square btn-sm lg:hidden focus-ring" aria-label="Open navigation">
          <Icon name="menu" />
        </label>
        <div className="flex items-center gap-2 lg:hidden">
          <span className="grid size-8 place-items-center rounded-lg bg-primary font-bangla text-sm font-bold text-primary-content">সা</span>
          <span className="font-extrabold tracking-wide">SATHI</span>
        </div>
        <div className="hidden min-w-0 flex-1 items-baseline gap-3 lg:flex">
          <h1 className="truncate text-base font-semibold lg:text-lg">{title}</h1>
          <span className="hidden truncate text-xs text-base-content/50 xl:inline">
            AI DEV FEST 2026 · Track 07
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {deployment?.simulated_only && (
          <span className="badge badge-outline border-warning bg-warning/20 text-base-content hidden py-3 text-xs font-medium md:inline-flex" title={deployment.label} data-testid="deployment-mode">
            Public simulated demo
          </span>
        )}
        <div className="tooltip tooltip-bottom" data-tip={status.label}>
          <span
            className="badge badge-ghost gap-2 border-base-300 py-3 font-medium focus-ring"
            title="Connection to the Sathi server"
            tabIndex={0}
            role="status"
          >
            <span
              className="inline-block size-2.5 shrink-0 rounded-full transition-colors"
              style={{ backgroundColor: status.color }}
            />
            <span className="hidden text-xs sm:inline">{status.label}</span>
            <span className="sr-only">{status.label}</span>
          </span>
        </div>

        {import.meta.env?.DEV && (
          <button
            className="btn btn-ghost btn-xs hidden md:inline-flex focus-ring"
            onClick={toggleEndpoint}
            title="Switch between live FastAPI (18000) and mock server (18001). Development only."
          >
            {currentUrl.includes('18001') ? 'Mock 18001' : 'Live 18000'}
          </button>
        )}

        <ThemeToggle />

        {session ? (
          <div className="dropdown dropdown-end">
            <div
              tabIndex={0}
              role="button"
              className="btn btn-ghost btn-sm gap-2 px-2 focus-ring"
              aria-label="Open account menu"
            >
              <span className={`grid size-7 place-items-center rounded-full ${role.tone}`}>
                <Icon name={role.icon} className="size-4" />
              </span>
              <span className="hidden text-left leading-tight sm:block">
                <span className="block text-xs font-semibold">{role.label}</span>
                <span className="block text-[11px] font-normal opacity-60">{phone(session.subject)}</span>
              </span>
            </div>
            <ul
              tabIndex={0}
              className="menu dropdown-content z-40 mt-2 w-56 rounded-box border border-base-300 bg-base-100 p-2 shadow-lg"
            >
              <li className="menu-title">{role.label} · {phone(session.subject)}</li>
              <li>
                <button onClick={() => onLogin()} className="focus-ring">
                  <Icon name="switch" className="size-4" />Switch user
                </button>
              </li>
              <li>
                <button onClick={onLogout} className="text-error focus-ring">
                  <Icon name="logout" className="size-4" />Sign out
                </button>
              </li>
            </ul>
          </div>
        ) : (
          <button className="btn btn-primary btn-sm focus-ring" onClick={() => onLogin()}>
            Sign in
          </button>
        )}
      </div>
    </header>
  );
}