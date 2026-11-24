import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ChatMessage } from '../ChatMessage';
import { apiFetch } from '../../../lib/apiClient';

jest.mock('../../../lib/apiClient', () => ({ apiFetch: jest.fn() }));

const source = 'zephyr_0123456789abcdef0123456789abcdef.pdf';
const message = {
  id: 'm1', sender: 'assistant', text: 'Closes on day 17.', sources: [source, source],
  timestamp: new Date().toISOString(),
};

afterEach(() => apiFetch.mockReset());

test('citation chip opens the indexed passages of its source', async () => {
  apiFetch.mockResolvedValue({
    ok: true, status: 200,
    json: async () => ({ filename: 'zephyr.pdf', department: 'finance',
      passages: ['The synthetic Zephyr ledger closes on day 17.'] }),
  });
  render(<ChatMessage message={message} userInitial="U" />);

  const chips = screen.getAllByRole('button', { name: /zephyr\.pdf/ });
  expect(chips).toHaveLength(1); // duplicate citations collapse to one chip
  fireEvent.click(chips[0]);

  expect(apiFetch).toHaveBeenCalledWith(`/api/documents/source/${encodeURIComponent(source)}`);
  expect(await screen.findByText(/Zephyr ledger closes on day 17/)).toBeInTheDocument();
  expect(screen.getByText('Department: finance')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Close source' }));
  await waitFor(() => expect(screen.queryByText(/Zephyr ledger/)).not.toBeInTheDocument());
});

test('a source the account cannot read shows a neutral message', async () => {
  apiFetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
  render(<ChatMessage message={message} userInitial="U" />);
  fireEvent.click(screen.getByRole('button', { name: /zephyr\.pdf/ }));
  expect(await screen.findByText('This source is no longer available, or your account cannot open it.')).toBeInTheDocument();
});
