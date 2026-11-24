import { useCallback, useSyncExternalStore } from 'react';

const STORAGE_KEY = 'finsolve.theme';
const THEMES = ['light', 'dark'];
const DEFAULT_THEME = 'dark';
const listeners = new Set();

const read = () => {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (THEMES.includes(stored)) return stored;
  } catch {
    /* storage unavailable: fall through to the default */
  }
  // Navy glass is the default for anyone without a saved preference; a saved
  // choice (light or dark) is always honoured. The OS setting is ignored so
  // the first impression is the same for everyone.
  return DEFAULT_THEME;
};

let current = typeof window === 'undefined' ? DEFAULT_THEME : read();

const apply = (theme) => {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', theme);
  }
};

/** Call once before first render so there is no flash of the wrong theme. */
export const initTheme = () => {
  current = read();
  apply(current);
};

const setTheme = (theme) => {
  if (!THEMES.includes(theme) || theme === current) return;
  current = theme;
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* preference just isn't remembered */
  }
  apply(theme);
  listeners.forEach((fn) => fn());
};

const subscribe = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

export default function useTheme() {
  const theme = useSyncExternalStore(subscribe, () => current, () => DEFAULT_THEME);
  const toggleTheme = useCallback(() => setTheme(current === 'dark' ? 'light' : 'dark'), []);
  return { theme, setTheme, toggleTheme };
}
