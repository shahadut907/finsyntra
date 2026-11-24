import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import AdminDashboard from '../AdminDashboard';

const Where = () => <div data-testid="where">{useLocation().pathname}</div>;
const apiCall = jest.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) });

const mount = (user) => render(
  <MemoryRouter initialEntries={['/admin']}>
    <Routes>
      <Route path="/admin" element={<AdminDashboard isOpen user={user} apiCall={apiCall} addNotification={jest.fn()} onClose={jest.fn()} />} />
      <Route path="/chat" element={<Where />} />
    </Routes>
  </MemoryRouter>
);

test('Super Admin sees Usage & Controls and an AI Chat link that opens the existing chat', async () => {
  mount({ name: 'Owner', role: 'admin', is_admin: true, is_super_admin: true });
  expect(await screen.findByTitle('Usage & Controls')).toBeInTheDocument();
  fireEvent.click(screen.getByTitle('AI Chat'));
  expect(screen.getByTestId('where')).toHaveTextContent('/chat');
});

test('other admins (including the public demo admin) get neither entry', async () => {
  mount({ name: 'Demo Admin', role: 'admin', is_admin: true, is_public_demo: true, is_super_admin: false });
  await screen.findByTitle('Overview');
  expect(screen.queryByTitle('Usage & Controls')).toBeNull();
  expect(screen.queryByTitle('AI Chat')).toBeNull();
});
