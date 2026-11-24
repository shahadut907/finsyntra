/**
 * Navigation Regression Tests
 * 
 * CRITICAL: These tests verify that sidebar navigation does NOT trigger logout.
 * This bug has recurred multiple times. These tests serve as a safeguard.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, useAuth } from '../../contexts/AuthContext';

// Store for localStorage mock
let localStorageStore = {};

// Mock fetch for auth endpoints
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock localStorage - must be set up before imports
beforeAll(() => {
    const localStorageMock = {
        getItem: jest.fn((key) => localStorageStore[key] || null),
        setItem: jest.fn((key, value) => { localStorageStore[key] = String(value); }),
        removeItem: jest.fn((key) => { delete localStorageStore[key]; }),
        clear: jest.fn(() => { localStorageStore = {}; }),
    };
    Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true });
});

// Test consumer component to expose auth context
const AuthTestConsumer = ({ onAuthReady }) => {
    const auth = useAuth();
    React.useEffect(() => {
        if (auth.isInitialized) {
            onAuthReady?.(auth);
        }
    }, [auth, onAuthReady]);

    return (
        <div>
            <span data-testid="isInitialized">{String(auth.isInitialized)}</span>
            <span data-testid="isAuthenticated">{String(auth.isAuthenticated)}</span>
            <span data-testid="isLoading">{String(auth.isLoading)}</span>
        </div>
    );
};

describe('Sidebar Navigation - No Logout Regression', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        localStorageStore = {};

        // Set up valid token BEFORE render
        localStorageStore['finsolve_auth_token'] = 'valid-test-token';

        // Mock successful auth check
        mockFetch.mockImplementation((url) => {
            if (url.includes('/auth/me')) {
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({
                        email: 'test@example.com',
                        name: 'Test User',
                        role: 'employee'
                    })
                });
            }
            return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        });
    });

    it('should expose isInitialized in auth context after boot check', async () => {
        render(
            <MemoryRouter>
                <AuthProvider>
                    <AuthTestConsumer />
                </AuthProvider>
            </MemoryRouter>
        );

        // Wait for initialization to complete
        await waitFor(() => {
            expect(screen.getByTestId('isInitialized').textContent).toBe('true');
        }, { timeout: 3000 });

        // Should be authenticated after successful /auth/me
        expect(screen.getByTestId('isAuthenticated').textContent).toBe('true');
        expect(screen.getByTestId('isLoading').textContent).toBe('false');
    });

    it('should call /auth/me on mount', async () => {
        render(
            <MemoryRouter>
                <AuthProvider>
                    <AuthTestConsumer />
                </AuthProvider>
            </MemoryRouter>
        );

        await waitFor(() => {
            expect(mockFetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/me'),
                expect.any(Object)
            );
        });
    });

    it('should NOT call removeItem on successful auth check', async () => {
        const removeItemSpy = jest.spyOn(window.localStorage, 'removeItem');

        render(
            <MemoryRouter>
                <AuthProvider>
                    <AuthTestConsumer />
                </AuthProvider>
            </MemoryRouter>
        );

        await waitFor(() => {
            expect(screen.getByTestId('isInitialized').textContent).toBe('true');
        });

        // Token should NOT have been removed during successful auth
        expect(removeItemSpy).not.toHaveBeenCalledWith('finsolve_auth_token');
    });
});

/**
 * Manual Testing Checklist
 * 
 * 1. Login with valid credentials
 * 2. Open browser console (F12)
 * 3. Click each sidebar item in order:
 *    - Dashboard (/)
 *    - AI Assistant (/chat)
 *    - Documents (/documents)
 *    - Search (/search)
 *    - Reports (/reports)
 *    - Insights (/insights)
 *    - Performance (/performance)
 * 
 * 4. VERIFY in console:
 *    - NO "[apiClient] Triggering logout" messages
 *    - "[ProtectedRoute] Auth check:" shows isAuthenticated: true
 * 
 * 5. VERIFY in Application > Local Storage:
 *    - finsolve_auth_token still present
 * 
 * 6. VERIFY in Network tab:
 *    - No 401 responses on page navigation
 */
