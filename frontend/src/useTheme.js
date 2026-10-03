import { useEffect, useState, useCallback } from 'react';

const STORAGE_KEY = 'sathi-theme';
const LIGHT = 'sathi';
const DARK = 'sathi-dark';

const storage = {
  get(key) {
    try {
      return globalThis.localStorage ? globalThis.localStorage.getItem(key) : null;
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      if (globalThis.localStorage) globalThis.localStorage.setItem(key, value);
    } catch {
      /* ignore quota or privacy mode errors */
    }
  },
};

const readInitial = () => {
  if (typeof document === 'undefined') return LIGHT;
  return document.documentElement.getAttribute('data-theme') || LIGHT;
};

const applyTheme = (theme) => {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('data-theme', theme);
  storage.set(STORAGE_KEY, theme);
};

export function useTheme() {
  const [theme, setTheme] = useState(readInitial);

  useEffect(() => {
    applyTheme(theme);
    if (typeof document !== 'undefined') {
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) {
        meta.setAttribute('content', theme === DARK ? '#1a2233' : '#0f766e');
      }
    }
  }, [theme]);

  // Track OS preference changes only when the user has not explicitly chosen.
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const handle = (event) => {
      if (!storage.get(STORAGE_KEY)) {
        setTheme(event.matches ? DARK : LIGHT);
      }
    };
    media.addEventListener('change', handle);
    return () => media.removeEventListener('change', handle);
  }, []);

  const toggle = useCallback(() => {
    setTheme((current) => (current === DARK ? LIGHT : DARK));
  }, []);

  const setLight = useCallback(() => setTheme(LIGHT), []);
  const setDark = useCallback(() => setTheme(DARK), []);

  return { theme, isDark: theme === DARK, toggle, setLight, setDark };
}

export const themes = { LIGHT, DARK };