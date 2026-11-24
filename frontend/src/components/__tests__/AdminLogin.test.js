/**
 * Admin Login Feature Tests
 * 
 * Tests the admin login checkbox feature:
 * 1. Checkbox visibility based on VITE_ENABLE_ADMIN_LOGIN env var
 * 2. Admin redirect on successful login with admin role
 * 3. Non-admin toast when user doesn't have admin privileges
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import LoginForm from '../LoginForm';

// Mock environment variable (Create React App uses process.env)
const originalEnv = process.env;

describe('Admin Login Feature', () => {
  
  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear();
  });

  afterEach(() => {
    // Restore environment
    process.env = originalEnv;
  });

  /**
   * Test 1: Checkbox is visible when REACT_APP_ENABLE_ADMIN_LOGIN is 'true'
   */
  test('renders admin checkbox when REACT_APP_ENABLE_ADMIN_LOGIN is true', () => {
    // Mock environment variable
    process.env = { ...originalEnv, REACT_APP_ENABLE_ADMIN_LOGIN: 'true' };
    
    const mockOnLogin = jest.fn();
    
    render(
      <BrowserRouter>
        <LoginForm 
          onLogin={mockOnLogin} 
          isLoading={false} 
          error={null} 
          darkMode={true} 
        />
      </BrowserRouter>
    );
    
    // Check if checkbox is rendered
    const checkbox = screen.getByLabelText(/sign in as admin/i);
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
    
    // Check if Shield icon label is present
    expect(screen.getByText('Sign in as admin')).toBeInTheDocument();
  });

  /**
   * Test 2: Checkbox is hidden when REACT_APP_ENABLE_ADMIN_LOGIN is not 'true'
   */
  test('hides admin checkbox when REACT_APP_ENABLE_ADMIN_LOGIN is not true', () => {
    // Mock environment variable as false
    process.env = { ...originalEnv, REACT_APP_ENABLE_ADMIN_LOGIN: 'false' };
    
    const mockOnLogin = jest.fn();
    
    render(
      <BrowserRouter>
        <LoginForm 
          onLogin={mockOnLogin} 
          isLoading={false} 
          error={null} 
          darkMode={true} 
        />
      </BrowserRouter>
    );
    
    // Checkbox should not be in the document
    const checkbox = screen.queryByLabelText(/sign in as admin/i);
    expect(checkbox).not.toBeInTheDocument();
  });

  /**
   * Test 3: Admin checkbox persists state in localStorage
   */
  test('persists admin checkbox state in localStorage', () => {
    process.env = { ...originalEnv, REACT_APP_ENABLE_ADMIN_LOGIN: 'true' };
    
    const mockOnLogin = jest.fn();
    
    const { rerender } = render(
      <BrowserRouter>
        <LoginForm 
          onLogin={mockOnLogin} 
          isLoading={false} 
          error={null} 
          darkMode={true} 
        />
      </BrowserRouter>
    );
    
    const checkbox = screen.getByLabelText(/sign in as admin/i);
    
    // Initially unchecked
    expect(checkbox).not.toBeChecked();
    expect(localStorage.getItem('finsolve.adminLogin')).toBeNull();
    
    // Check the checkbox
    fireEvent.click(checkbox);
    
    // Should be checked and persisted
    expect(checkbox).toBeChecked();
    expect(localStorage.getItem('finsolve.adminLogin')).toBe('true');
    
    // Rerender component - should restore from localStorage
    rerender(
      <BrowserRouter>
        <LoginForm 
          onLogin={mockOnLogin} 
          isLoading={false} 
          error={null} 
          darkMode={true} 
        />
      </BrowserRouter>
    );
    
    const checkboxAfterRerender = screen.getByLabelText(/sign in as admin/i);
    expect(checkboxAfterRerender).toBeChecked();
  });

  /**
   * Test 4: Login with admin checkbox checked passes adminIntent
   */
  test('passes adminIntent to onLogin when checkbox is checked', async () => {
    process.env = { ...originalEnv, REACT_APP_ENABLE_ADMIN_LOGIN: 'true' };
    
    const mockOnLogin = jest.fn();
    
    render(
      <BrowserRouter>
        <LoginForm 
          onLogin={mockOnLogin} 
          isLoading={false} 
          error={null} 
          darkMode={true} 
        />
      </BrowserRouter>
    );
    
    // Fill in credentials
    const emailInput = screen.getByLabelText(/email address/i);
    const passwordInput = screen.getByLabelText(/password/i);
    
    fireEvent.change(emailInput, { target: { value: 'admin@test.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    
    // Check admin checkbox
    const checkbox = screen.getByLabelText(/sign in as admin/i);
    fireEvent.click(checkbox);
    
    // Submit form
    const submitButton = screen.getByRole('button', { name: /sign in/i });
    fireEvent.click(submitButton);
    
    // Verify onLogin was called with adminIntent
    await waitFor(() => {
      expect(mockOnLogin).toHaveBeenCalledWith(
        expect.objectContaining({
          username: 'admin@test.com',
          password: 'password123',
          adminIntent: true
        })
      );
    });
  });

  /**
   * Test 5: Login without admin checkbox doesn't pass adminIntent
   */
  test('does not pass adminIntent when checkbox is unchecked', async () => {
    process.env = { ...originalEnv, REACT_APP_ENABLE_ADMIN_LOGIN: 'true' };
    
    const mockOnLogin = jest.fn();
    
    render(
      <BrowserRouter>
        <LoginForm 
          onLogin={mockOnLogin} 
          isLoading={false} 
          error={null} 
          darkMode={true} 
        />
      </BrowserRouter>
    );
    
    // Fill in credentials (don't check admin box)
    const emailInput = screen.getByLabelText(/email address/i);
    const passwordInput = screen.getByLabelText(/password/i);
    
    fireEvent.change(emailInput, { target: { value: 'user@test.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    
    // Submit form
    const submitButton = screen.getByRole('button', { name: /sign in/i });
    fireEvent.click(submitButton);
    
    // Verify onLogin was called with adminIntent: false
    await waitFor(() => {
      expect(mockOnLogin).toHaveBeenCalledWith(
        expect.objectContaining({
          username: 'user@test.com',
          password: 'password123',
          adminIntent: false
        })
      );
    });
  });

  /**
   * Test 6: Dev mode logging
   */
  test('logs AdminLoginIntent in development mode', async () => {
    process.env = { ...originalEnv, REACT_APP_ENABLE_ADMIN_LOGIN: 'true' };
    
    // Save original NODE_ENV
    const originalNodeEnv = process.env.NODE_ENV;
    process.env.NODE_ENV = 'development';
    
    const consoleSpy = jest.spyOn(console, 'log').mockImplementation();
    const mockOnLogin = jest.fn();
    
    render(
      <BrowserRouter>
        <LoginForm 
          onLogin={mockOnLogin} 
          isLoading={false} 
          error={null} 
          darkMode={true} 
        />
      </BrowserRouter>
    );
    
    // Fill credentials and check admin box
    const emailInput = screen.getByLabelText(/email address/i);
    const passwordInput = screen.getByLabelText(/password/i);
    const checkbox = screen.getByLabelText(/sign in as admin/i);
    
    fireEvent.change(emailInput, { target: { value: 'admin@test.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.click(checkbox);
    
    // Submit
    const submitButton = screen.getByRole('button', { name: /sign in/i });
    fireEvent.click(submitButton);
    
    // Check console log was called
    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('AdminLoginIntent:', true);
    });
    
    // Cleanup
    consoleSpy.mockRestore();
    process.env.NODE_ENV = originalNodeEnv;
  });
});

/**
 * Integration Test Scenarios (Manual Testing Guide)
 * 
 * Scenario 1: Admin user with checkbox
 * - Checkbox: ON
 * - User role: admin
 * - Expected: Redirect to /admin
 * 
 * Scenario 2: Non-admin user with checkbox
 * - Checkbox: ON
 * - User role: employee
 * - Expected: Toast "Your account doesn't have admin access.", redirect to /chat
 * 
 * Scenario 3: Admin user without checkbox
 * - Checkbox: OFF
 * - User role: admin
 * - Expected: Redirect to /chat (normal flow)
 * 
 * Scenario 4: Non-admin user without checkbox
 * - Checkbox: OFF
 * - User role: employee
 * - Expected: Redirect to /chat (normal flow)
 * 
 * Scenario 5: C-level user with checkbox
 * - Checkbox: ON
 * - User role: c_level
 * - Expected: Redirect to /admin (c_level treated as admin)
 */

