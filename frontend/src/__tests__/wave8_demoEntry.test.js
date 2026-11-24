import React from 'react';
import { render, screen } from '@testing-library/react';
import LoginForm from '../components/LoginForm';

// Landing "Try Demo" links to /app/login?demo=1. When this build has no demo
// panel, the login page must say so rather than show a bare sign-in form.
const renderLogin = () =>
  render(
    <LoginForm
      onLogin={jest.fn()}
      onDemoLogin={jest.fn()}
      isLoading={false}
      error={null}
      darkMode
    />
  );

describe('demo entry from the landing page', () => {
  const previousFlag = process.env.REACT_APP_PUBLIC_DEMO_ENABLED;
  const previousUrl = window.location.href;

  afterEach(() => {
    process.env.REACT_APP_PUBLIC_DEMO_ENABLED = previousFlag;
    window.history.replaceState({}, '', previousUrl);
  });

  test('explains unavailable demo when ?demo=1 and the build has no demo panel', () => {
    process.env.REACT_APP_PUBLIC_DEMO_ENABLED = 'false';
    window.history.replaceState({}, '', '/app/login?demo=1');
    renderLogin();

    expect(screen.getByRole('alert')).toHaveTextContent(/demo access is not enabled/i);
    expect(screen.queryByRole('region', { name: /public demo personas/i })).toBeNull();
  });

  test('shows no notice for a plain sign-in when the demo panel is off', () => {
    process.env.REACT_APP_PUBLIC_DEMO_ENABLED = 'false';
    window.history.replaceState({}, '', '/app/login');
    renderLogin();

    expect(screen.queryByText(/demo access is not enabled/i)).toBeNull();
  });

  test('shows the labeled demo panel with ?demo=1 when the demo is enabled', () => {
    process.env.REACT_APP_PUBLIC_DEMO_ENABLED = 'true';
    window.history.replaceState({}, '', '/app/login?demo=1');
    renderLogin();

    expect(screen.getByRole('region', { name: /public demo personas/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue as admin/i })).toBeInTheDocument();
    expect(screen.queryByText(/demo access is not enabled/i)).toBeNull();
  });
});
