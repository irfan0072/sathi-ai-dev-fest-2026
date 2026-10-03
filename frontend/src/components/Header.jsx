import { useState, useEffect } from 'react';
import { API_BASE_URL, setApiBaseUrl, api } from '../api';
import Icon from './Icon';
import { roleMeta } from './DemoLogin';

const health = {
  unknown: { color: '#94a3b8', label: 'Connecting to API...' }, // never green until verified
  healthy: { color: '#10b981', label: 'Live Backend Connected' },
  unhealthy: { color: '#f43f5e', label: 'API Offline / Disconnected' },
};

export default function Header({ title = '', session = null, onLogin = () => {}, onLogout = () => {} }) {
  const [healthStatus, setHealthStatus] = useState('unknown');
  const [currentUrl, setCurrentUrl] = useState(API_BASE_URL);

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
    <header className="navbar sticky top-0 z-30 gap-2 border-b border-base-300 bg-base-100/90 px-3 backdrop-blur sm:px-6">
      <div className="flex flex-1 items-center gap-2 min-w-0">
        <label htmlFor="sathi-drawer" className="btn btn-ghost btn-square btn-sm lg:hidden" aria-label="Open navigation">
          <Icon name="menu" />
        </label>
        <div className="flex items-center gap-2 lg:hidden">
          <span className="grid size-8 place-items-center rounded-lg bg-primary font-bangla text-sm font-bold text-primary-content">সা</span>
          <span className="font-extrabold tracking-wide">SATHI</span>
        </div>
        <h1 className="hidden truncate text-base font-semibold lg:block">{title}</h1>
      </div>

      <div className="flex items-center gap-2">
        <div className="tooltip tooltip-bottom" data-tip={status.label}>
          <span className="badge badge-ghost gap-2 border-base-300 py-3" title="Backend API health">
            <span className="inline-block size-2.5 rounded-full" style={{ backgroundColor: status.color }} />
            <span className="hidden text-xs sm:inline">{status.label}</span>
          </span>
        </div>

        {import.meta.env?.DEV && (
          <button className="btn btn-ghost btn-xs hidden md:inline-flex" onClick={toggleEndpoint}
            title="Switch between live FastAPI (18000) and mock server (18001). Development only.">
            {currentUrl.includes('18001') ? 'Mock 18001' : 'Live 18000'}
          </button>
        )}

        {session ? (
          <div className="dropdown dropdown-end">
            <div tabIndex={0} role="button" className="btn btn-ghost btn-sm gap-2 px-2">
              <span className={`grid size-7 place-items-center rounded-full ${role.tone}`}>
                <Icon name={role.icon} className="size-4" />
              </span>
              <span className="hidden text-left leading-tight sm:block">
                <span className="block text-xs font-semibold">{role.label}</span>
                <span className="block text-[11px] font-normal opacity-60">{session.subject}</span>
              </span>
            </div>
            <ul tabIndex={0} className="menu dropdown-content z-40 mt-2 w-56 rounded-box border border-base-300 bg-base-100 p-2 shadow-lg">
              <li className="menu-title">{role.label} · {session.subject}</li>
              <li><button onClick={() => onLogin()}><Icon name="switch" className="size-4" />Switch role</button></li>
              <li><button onClick={onLogout} className="text-error"><Icon name="logout" className="size-4" />Sign out</button></li>
            </ul>
          </div>
        ) : (
          <button className="btn btn-primary btn-sm" onClick={() => onLogin()}>Sign in</button>
        )}
      </div>
    </header>
  );
}
