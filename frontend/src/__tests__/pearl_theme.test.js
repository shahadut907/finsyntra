import React from 'react';
import fs from 'fs';
import path from 'path';
import { render, screen, fireEvent, act } from '@testing-library/react';
import useTheme, { initTheme } from '../hooks/useTheme';

jest.mock('../lib/apiClient', () => ({ apiFetch: jest.fn() }));
const { apiFetch } = require('../lib/apiClient');

const css = fs.readFileSync(path.join(__dirname, '../styles/glass.css'), 'utf8');

const Probe = () => {
  const { theme, toggleTheme } = useTheme();
  return <button onClick={toggleTheme}>theme:{theme}</button>;
};

describe('theme tokens', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  test('defaults to navy glass and applies data-theme before render', () => {
    act(() => initTheme());
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  test('toggle switches to light, persists, and updates <html>', () => {
    act(() => initTheme());
    render(<Probe />);
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('button').textContent).toBe('theme:light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(window.localStorage.getItem('finsolve.theme')).toBe('light');
    fireEvent.click(screen.getByRole('button'));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  test('a saved light preference is not overridden by the new default', () => {
    window.localStorage.setItem('finsolve.theme', 'light');
    act(() => initTheme());
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  test('glass.css defines both themes and a no-backdrop-filter fallback', () => {
    expect(css).toMatch(/:root\s*{[^}]*color-scheme: light/);
    expect(css).toMatch(/\[data-theme='dark'\]\s*{[^}]*color-scheme: dark/);
    expect(css).toMatch(/@supports not \(\(backdrop-filter/);
  });

  test('component rules below the token block use tokens, not raw colors', () => {
    const body = css.slice(css.indexOf('App shell'));
    const legacyBlock = body.indexOf('Legacy Tailwind colour utilities');
    const checked = body.slice(0, legacyBlock);
    // Gradient sheens and the primary-button highlight are intentional white
    // overlays; nothing else may hardcode a colour.
    const stripped = checked.replace(/rgba\(255, 255, 255, [^)]*\)/g, '');
    expect(stripped).not.toMatch(/#[0-9a-fA-F]{6}\b/);
    expect(stripped).not.toMatch(/rgba\((?!\s*0,\s*0,\s*0)/);
  });
});

describe('ChatWelcome', () => {
  // eslint-disable-next-line global-require
  const ChatWelcome = require('../components/chat/ChatWelcome').default;

  test('leads with the greeting and prefills the composer from a suggestion', async () => {
    // CRA resets mock implementations between tests, so set it here.
    apiFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ total_documents: 3 }) });
    const onPromptSelect = jest.fn();
    render(<ChatWelcome user={{ name: 'Demo Admin', role: 'admin' }} onPromptSelect={onPromptSelect} />);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(/Admin/);
    expect(screen.queryByText(/Demo/)).toBeNull();
    const first = screen.getAllByRole('button')[0];
    fireEvent.click(first);
    expect(onPromptSelect).toHaveBeenCalledWith(first.textContent.trim());
    expect(await screen.findByText(/3 documents indexed/)).toBeTruthy();
  });
});
