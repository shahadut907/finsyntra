import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import LoginForm from '../components/LoginForm';


describe('Wave 7 public demo login', () => {
  const previous = process.env.REACT_APP_PUBLIC_DEMO_ENABLED;

  beforeEach(() => {
    process.env.REACT_APP_PUBLIC_DEMO_ENABLED = 'true';
  });

  afterAll(() => {
    process.env.REACT_APP_PUBLIC_DEMO_ENABLED = previous;
  });

  test('offers explicit Admin and Employee perspectives without credentials', () => {
    const onDemoLogin = jest.fn();
    render(
      <LoginForm
        onLogin={jest.fn()}
        onDemoLogin={onDemoLogin}
        isLoading={false}
        error={null}
        darkMode
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /continue as admin/i }));
    fireEvent.click(screen.getByRole('button', { name: /continue as employee/i }));

    expect(onDemoLogin).toHaveBeenNthCalledWith(1, 'admin');
    expect(onDemoLogin).toHaveBeenNthCalledWith(2, 'employee');
    expect(screen.getByText(/admin mutations are disabled in public demo/i)).toBeInTheDocument();
  });

  test('offers explicit Finance, HR, and Engineering perspectives without credentials', () => {
    const onDemoLogin = jest.fn();
    render(
      <LoginForm
        onLogin={jest.fn()}
        onDemoLogin={onDemoLogin}
        isLoading={false}
        error={null}
        darkMode
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /continue as finance/i }));
    fireEvent.click(screen.getByRole('button', { name: /continue as hr/i }));
    fireEvent.click(screen.getByRole('button', { name: /continue as engineering/i }));

    expect(onDemoLogin).toHaveBeenNthCalledWith(1, 'finance');
    expect(onDemoLogin).toHaveBeenNthCalledWith(2, 'hr');
    expect(onDemoLogin).toHaveBeenNthCalledWith(3, 'engineering');
  });
});
