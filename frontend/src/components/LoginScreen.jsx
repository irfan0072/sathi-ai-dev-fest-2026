import { useEffect } from 'react';
import Icon from './Icon';
import ThemeToggle from './ThemeToggle';
import DemoLogin from './DemoLogin';
import { roleMeta } from './DemoLogin';

const features = [
  {
    icon: 'flow',
    title: 'No PIN sharing',
    body: 'The customer never tells their PIN to anyone. They confirm the amount themselves, and the agent gets a code that works only once.',
  },
  {
    icon: 'shield',
    title: 'Secret help signal',
    body: 'If someone forces the customer, they type 0 before the amount (like 03000). Everything looks normal, but the cash is stopped and a supervisor is alerted.',
  },
  {
    icon: 'chart',
    title: 'Extra checks when something looks wrong',
    body: 'When a request looks risky, the customer is asked to confirm by phone. People, not the AI, make the final decision.',
  },
];

export default function LoginScreen({ onSuccess }) {
  // Pre-select the most common role on first render. Re-use the existing
  // roleMeta so the DemoLogin cards stay in sync with the rest of the app.
  useEffect(() => {
    // Avoid showing the synthetic-demo warning banner behind the login card.
    document.documentElement.setAttribute('data-login-screen', 'true');
    return () => document.documentElement.removeAttribute('data-login-screen');
  }, []);

  const handleDone = () => {
    if (typeof onSuccess === 'function') onSuccess();
  };

  return (
    <div className="min-h-screen w-full bg-base-200">
      <div className="grid min-h-screen w-full md:grid-cols-2">
        {/* Brand panel — hidden on small screens */}
        <aside className="relative hidden flex-col justify-between border-r border-base-300 bg-gradient-to-br from-primary/10 via-base-100 to-base-200 p-10 lg:p-14 md:flex">
          <header className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="grid size-12 place-items-center rounded-2xl bg-primary font-bangla text-2xl font-bold text-primary-content shadow-md">
                সাথী
              </span>
              <div className="leading-tight">
                <div className="text-2xl font-extrabold tracking-wide">SATHI</div>
                <div className="text-xs text-base-content/60">Safe cash-out, no PIN sharing</div>
              </div>
            </div>
            <ThemeToggle />
          </header>

          <div className="flex flex-col gap-8">
            <div>
              <h2 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
                Safe cash-out for <br className="hidden lg:block" />
                people who need help
              </h2>
              <p className="page-lead mt-3 max-w-md">
                Many people ask an agent to help them withdraw money and end up sharing their PIN.
                Sathi lets them get cash safely without ever sharing it.
              </p>
            </div>

            <ul className="flex flex-col gap-4">
              {features.map((item) => (
                <li key={item.title} className="flex items-start gap-3">
                  <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-base-200 text-primary">
                    <Icon name={item.icon} className="size-5" />
                  </span>
                  <div>
                    <div className="text-sm font-semibold">{item.title}</div>
                    <div className="muted text-sm leading-relaxed">{item.body}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <footer className="flex flex-wrap items-center justify-between gap-2 text-xs text-base-content/60">
            <span>
              Track 07 · AI DEV FEST 2026 · DIU CPC × upay
            </span>
            <span className="badge badge-ghost border-base-300">Demo with made-up data</span>
          </footer>
        </aside>

        {/* Login form */}
        <main className="flex items-center justify-center px-4 py-10 sm:px-8 lg:px-16">
          <div className="w-full max-w-md animate-fadeIn">
            <div className="mb-6 flex items-center justify-between md:hidden">
              <div className="flex items-center gap-2">
                <span className="grid size-9 place-items-center rounded-xl bg-primary font-bangla text-base font-bold text-primary-content">
                  সা
                </span>
                <span className="font-extrabold tracking-wide">SATHI</span>
              </div>
              <ThemeToggle />
            </div>

            <div className="panel shadow-md">
              <div className="panel-body gap-4 p-6 sm:p-8">
                <header className="flex flex-col gap-1">
                  <h1 className="text-2xl font-bold tracking-tight">Sign in</h1>
                  <p className="text-sm text-base-content/70">
                    Choose who you are. You can switch any time.
                  </p>
                </header>

                <DemoLogin onDone={handleDone} />

                <div className="divider my-0" />

                <div className="flex flex-col gap-2 text-xs text-base-content/60">
                  <div className="flex items-center gap-2 font-medium">
                    <Icon name="info" className="size-4" />
                    Demo PINs (for trying it out)
                  </div>
                  <ul className="ml-6 flex flex-col gap-1 font-mono">
                    <li>
                      <span className="inline-block w-32 font-sans font-medium text-base-content/70">
                        Agent
                      </span>
                      <span>1234</span>
                    </li>
                    <li>
                      <span className="inline-block w-32 font-sans font-medium text-base-content/70">
                        Customer
                      </span>
                      <span>5678</span>
                    </li>
                    <li>
                      <span className="inline-block w-32 font-sans font-medium text-base-content/70">
                        Supervisor
                      </span>
                      <span>9012</span>
                    </li>
                  </ul>
                </div>
              </div>
            </div>

            <p className="muted mt-6 text-center">
              This is a demo. All people and money here are made up.
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}

// Role helper — keep in sync with `tabs` array in NavTabs.jsx
export const ROLE_LANDING = {
  agent: 'simulation',
  customer_channel: 'simulation',
  analyst: 'command',
};

export const landingTabForRole = (role) => ROLE_LANDING[role] || 'simulation';

// Pure role listing for any future place that needs it
export const roleOptions = Object.entries(roleMeta).map(([id, meta]) => ({ id, ...meta }));