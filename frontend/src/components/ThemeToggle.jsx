import { useTheme } from '../useTheme';

const SunIcon = (props) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1.8}
    stroke="currentColor"
    className={props.className || 'size-5'}
    aria-hidden="true"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M12 3v2.25m0 13.5V21m-7.5-9h2.25m13.5 0H21M5.636 5.636l1.591 1.591m9.546 9.546l1.591 1.591M5.636 18.364l1.591-1.591m9.546-9.546l1.591-1.591M12 8.25a3.75 3.75 0 100 7.5 3.75 3.75 0 000-7.5z"
    />
  </svg>
);

const MoonIcon = (props) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1.8}
    stroke="currentColor"
    className={props.className || 'size-5'}
    aria-hidden="true"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z"
    />
  </svg>
);

export default function ThemeToggle({ variant = 'icon' }) {
  const { isDark, toggle } = useTheme();
  const label = isDark ? 'Switch to light mode' : 'Switch to dark mode';

  if (variant === 'switch') {
    return (
      <label
        className="swap swap-rotate btn btn-ghost btn-sm btn-circle focus-ring"
        aria-label={label}
        title={label}
      >
        <input
          type="checkbox"
          className="theme-controller"
          checked={isDark}
          onChange={toggle}
          aria-label={label}
        />
        <SunIcon className="swap-off size-5 theme-toggle-icon" />
        <MoonIcon className="swap-on size-5 theme-toggle-icon" />
      </label>
    );
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      className="btn btn-ghost btn-sm btn-circle focus-ring"
    >
      <span className="theme-toggle-icon" key={isDark ? 'moon' : 'sun'}>
        {isDark ? <SunIcon className="size-5" /> : <MoonIcon className="size-5" />}
      </span>
    </button>
  );
}
