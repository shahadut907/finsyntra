import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import DemoUsageMeter, { DEMO_USAGE_REFRESH_EVENT } from '../DemoUsageMeter';
import { apiFetch } from '../../../lib/apiClient';

jest.mock('../../../lib/apiClient', () => ({ apiFetch: jest.fn() }));

const usage = (over = {}) => ({
  enabled: true, limit: 10, used: 3, remaining: 7, percent: 30,
  resets_at: '2026-11-25T00:00:00+00:00', seconds_until_reset: 5400, ...over,
});
const reply = (body) => ({ ok: true, status: 200, json: async () => body });

afterEach(() => apiFetch.mockReset());

test('shows remaining messages, percentage and reset details', async () => {
  apiFetch.mockResolvedValue(reply(usage()));
  render(<DemoUsageMeter />);
  expect(await screen.findByText('7 of 10 demo messages left today')).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '30');

  fireEvent.click(screen.getByRole('button', { name: /demo messages left/ }));
  expect(screen.getByText('3 of 10')).toBeInTheDocument();
  expect(screen.getByText('30%')).toBeInTheDocument();
  expect(screen.getByText(/in 1h 30m/)).toBeInTheDocument();
});

test('reports an exhausted allowance and refreshes after a chat', async () => {
  apiFetch.mockResolvedValueOnce(reply(usage()));
  render(<DemoUsageMeter />);
  await screen.findByText('7 of 10 demo messages left today');

  apiFetch.mockResolvedValueOnce(reply(usage({ used: 10, remaining: 0, percent: 100 })));
  act(() => { window.dispatchEvent(new Event(DEMO_USAGE_REFRESH_EVENT)); });
  expect(await screen.findByText('Daily demo messages used up')).toBeInTheDocument();
});

test('renders nothing for private accounts, when disabled, or when the call fails', async () => {
  apiFetch.mockResolvedValue(reply({ enabled: false }));
  const { container, rerender } = render(<DemoUsageMeter />);
  await waitFor(() => expect(apiFetch).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();

  apiFetch.mockClear();
  rerender(<DemoUsageMeter enabled={false} />);
  expect(apiFetch).not.toHaveBeenCalled();
  expect(container).toBeEmptyDOMElement();

  apiFetch.mockRejectedValue(new Error('offline'));
  rerender(<DemoUsageMeter enabled />);
  await waitFor(() => expect(apiFetch).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});
