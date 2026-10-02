import { useState, useEffect } from 'react';
import { API_BASE_URL, setApiBaseUrl, api } from '../api';

export default function Header() {
  const [healthStatus, setHealthStatus] = useState('unknown'); // 'unknown' | 'healthy' | 'unhealthy'
  const [currentUrl, setCurrentUrl] = useState(API_BASE_URL);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      const ok = await api.checkHealth();
      if (mounted) {
        setHealthStatus(ok ? 'healthy' : 'unhealthy');
      }
    };
    check();
    const interval = setInterval(check, 5000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [currentUrl]);

  const toggleEndpoint = () => {
    const nextUrl = currentUrl.includes(':18000')
      ? 'http://127.0.0.1:18001'
      : 'http://127.0.0.1:18000';
    const changed = setApiBaseUrl(nextUrl);
    if (changed) {
      setCurrentUrl(nextUrl);
    }
  };

  const getStatusColor = () => {
    if (healthStatus === 'healthy') return '#10b981';
    if (healthStatus === 'unhealthy') return '#f43f5e';
    return '#94a3b8'; // Unknown status: slate grey, never green until verified
  };

  const getStatusLabel = () => {
    if (healthStatus === 'healthy') return 'Live Backend Connected';
    if (healthStatus === 'unhealthy') return 'API Offline / Disconnected';
    return 'Connecting to API...';
  };

  return (
    <header className="top-header">
      <div className="brand-section">
        <div className="logo-badge">সাথী</div>
        <div className="brand-title">
          <h1>
            SATHI <span style={{ fontSize: '0.85rem', color: '#10b981', fontWeight: 600 }}>[AI DEV FEST 2026]</span>
          </h1>
          <span className="brand-subtitle">
            AI-Assisted Scoped Mandates & Skimming Anomaly Detection • DIU CPC x upay
          </span>
        </div>
      </div>

      <div className="header-controls">
        <div className="status-badge" title="Backend API Health Connection">
          <span className="status-pulse" style={{ backgroundColor: getStatusColor() }}></span>
          <span>{getStatusLabel()}</span>
        </div>

        {import.meta.env?.DEV && (
          <button
            className="api-toggle-btn"
            onClick={toggleEndpoint}
            title="Switch between Live FastAPI (18000) and Standalone Mock Server (18001) [Dev Only]"
          >
            {currentUrl.includes('18001') ? 'Mock API (18001)' : 'Live API (18000)'} ⇄
          </button>
        )}
      </div>
    </header>
  );
}
