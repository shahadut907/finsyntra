import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import UsageControls from '../UsageControls';

const overview = (over = {}) => ({
  day: '2026-11-24', resets_at: '2026-11-25T00:00:00+00:00',
  public_access: { paused: false, until: null, message: null },
  messages: { used: 12, limit: 60, remaining: 48, percent: 20 },
  tokens: { public_used: 5000, public_cap: 140000, public_remaining: 135000, admin_used: 100, admin_reserve: 40000, admin_remaining: 39900, daily_budget: 180000 },
  unique_visitors_today: 4, unique_networks_today: 3, active_requests: 1,
  config: {
    visitor_daily_limit: 10, ip_daily_limit: 20, global_daily_limit: 60, daily_token_budget: 180000, super_admin_token_reserve: 40000,
    bounds: { visitor_daily_limit: { min: 1, max: 100 }, ip_daily_limit: { min: 1, max: 500 }, global_daily_limit: { min: 1, max: 1000 },
      daily_token_budget: { min: 1000, max: 200000 }, super_admin_token_reserve: { min: 0, max: 200000 } },
    overridden: [], pause: { paused: false }, fixed: { per_ip_per_minute: 3, max_concurrent_ai: 2 },
  },
  history: [{ day: '2026-11-24', messages: 12, tokens: 5000 }], ...over,
});
const reply = (body, ok = true) => ({ ok, status: ok ? 200 : 403, json: async () => body });

test('shows usage, quotas, active requests and limits', async () => {
  const apiCall = jest.fn().mockResolvedValue(reply(overview()));
  render(<UsageControls apiCall={apiCall} addNotification={jest.fn()} />);
  expect(await screen.findByText('12 / 60')).toBeInTheDocument();
  expect(screen.getByText('5,000 / 140,000')).toBeInTheDocument();
  expect(screen.getByText('100 / 40,000')).toBeInTheDocument();
  expect(screen.getByTestId('active-requests')).toHaveTextContent('1');
  expect(screen.getByLabelText('Messages per visitor / day')).toHaveValue(10);
  expect(screen.getByTestId('access-state')).toHaveTextContent('Open to visitors');
});

test('saves only the changed limits, resets counters and pauses', async () => {
  window.confirm = jest.fn(() => true);
  const apiCall = jest.fn().mockResolvedValue(reply(overview()));
  const notify = jest.fn();
  render(<UsageControls apiCall={apiCall} addNotification={notify} />);
  await screen.findByText('12 / 60');

  fireEvent.change(screen.getByLabelText('Messages per visitor / day'), { target: { value: '5' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save limits' }));
  await waitFor(() => expect(apiCall).toHaveBeenCalledWith('/admin/demo-usage/limits',
    expect.objectContaining({ method: 'PUT', body: JSON.stringify({ visitor_daily_limit: 5 }) })));

  await waitFor(() => expect(screen.getByRole('button', { name: 'Reset counters' })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: 'Reset counters' }));
  await waitFor(() => expect(apiCall).toHaveBeenCalledWith('/admin/demo-usage/reset',
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ scope: 'visitors' }) })));

  await waitFor(() => expect(screen.getByRole('button', { name: 'Pause public demo' })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: 'Pause public demo' }));
  await waitFor(() => expect(apiCall).toHaveBeenCalledWith('/admin/demo-usage/access',
    expect.objectContaining({ method: 'PUT', body: JSON.stringify({ enabled: false, pause_minutes: 60, message: null }) })));
});

test('offers resume while paused and reports a rejected change', async () => {
  const paused = overview({ public_access: { paused: true, until: '2026-11-24T20:00:00+00:00', message: null } });
  const apiCall = jest.fn().mockResolvedValueOnce(reply(paused)).mockResolvedValue(reply({ detail: { message: 'Nope' } }, false));
  const notify = jest.fn();
  render(<UsageControls apiCall={apiCall} addNotification={notify} />);
  expect(await screen.findByText(/Paused until/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Resume public demo' }));
  await waitFor(() => expect(notify).toHaveBeenCalledWith('Nope', 'error'));
});

test('shows the server refusal for non Super Admins', async () => {
  const apiCall = jest.fn().mockResolvedValue(reply({ detail: { message: 'Super Administrator access required' } }, false));
  render(<UsageControls apiCall={apiCall} addNotification={jest.fn()} />);
  expect(await screen.findByText('Super Administrator access required')).toBeInTheDocument();
});
