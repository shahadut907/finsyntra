import { render, screen } from '@testing-library/react';
import App from './App';

test('renders the authenticated-app initialization state', () => {
  // The router is mounted under the /app basename (package.json "homepage").
  window.history.pushState({}, '', '/app/');
  render(<App />);
  expect(screen.getByText(/loading/i)).toBeInTheDocument();
});
