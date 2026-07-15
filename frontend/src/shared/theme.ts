export type ThemeSetting = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'ctrlrunner-theme';

export function themeSetting(): ThemeSetting {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return 'system';
}

function resolved(setting: ThemeSetting): 'light' | 'dark' {
  if (setting === 'system')
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  return setting;
}

export function applyTheme(setting: ThemeSetting = themeSetting()): void {
  const mode = resolved(setting);
  const root = document.documentElement;
  root.classList.toggle('theme-dark', mode === 'dark');
  root.classList.toggle('theme-light', mode === 'light');
}

export function setThemeSetting(setting: ThemeSetting): void {
  localStorage.setItem(STORAGE_KEY, setting);
  applyTheme(setting);
}

export function cycleTheme(): ThemeSetting {
  const order: ThemeSetting[] = ['system', 'light', 'dark'];
  const next = order[(order.indexOf(themeSetting()) + 1) % order.length];
  setThemeSetting(next);
  return next;
}

export function currentMode(): 'light' | 'dark' {
  return document.documentElement.classList.contains('theme-dark') ? 'dark' : 'light';
}

// Follow OS changes while the setting is "system".
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (themeSetting() === 'system') applyTheme();
});
