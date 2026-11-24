import React, { createContext, useState, useContext, useEffect, useCallback } from 'react';
import { API_BASE, apiFetch, getCsrfToken, refreshSession, setAuthErrorCallback } from '../lib/apiClient';

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // Boot check: verify existing session on mount
  const checkAuth = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      const response = await apiFetch('/auth/me', {
        method: 'GET',
        credentials: 'include',
        headers: {
          'Accept': 'application/json',
        },
      });

      if (response.ok) {
        const userData = await response.json();
        setUser(userData);
        setIsAuthenticated(true);
        console.log('✅ Auth boot check: authenticated', userData.email);
      } else {
        // Not authenticated - clear state
        setUser(null);
        setIsAuthenticated(false);
        console.log('⚠️ Auth boot check: not authenticated (401)');
      }
    } catch (err) {
      console.error('❌ Auth boot check failed:', err);
      setUser(null);
      setIsAuthenticated(false);
    } finally {
      setIsLoading(false);
      setIsInitialized(true);
      console.log('✅ Auth initialization complete');
    }
  }, []);

  // Login function
  const login = useCallback(async (credentials) => {
    try {
      setIsLoading(true);
      setError(null);

      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username: credentials.username,
          email: credentials.username,  // Send both for compatibility
          password: credentials.password,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));

        // Handle structured error response where detail is an object with message
        if (errorData.detail && typeof errorData.detail === 'object' && errorData.detail.message) {
          throw new Error(errorData.detail.message);
        }

        // Handle direct message field
        if (errorData.message) {
          throw new Error(errorData.message);
        }

        // Handle 422 validation errors (array)
        if (response.status === 422 && Array.isArray(errorData.detail)) {
          const firstError = errorData.detail[0];
          throw new Error(firstError.msg || 'Please check your input');
        }

        // Handle string detail
        if (typeof errorData.detail === 'string') {
          throw new Error(errorData.detail);
        }

        // Final fallback
        throw new Error('Login failed. Please try again.');
      }

      const data = await response.json();

      // Access token is stored as httpOnly cookie by the backend.
      // We keep a transient in-memory reference for debug tracing only.
      if (data.access_token) {
        console.log('✅ Access token received (stored via httpOnly cookie)');
      }

      // Get CSRF token from cookie if available
      const csrfToken = getCsrfToken();
      if (csrfToken) {
        console.log('✅ CSRF token found in cookie');
      }

      // Fetch user data from /auth/me
      const meResponse = await apiFetch('/auth/me', {
        method: 'GET',
        credentials: 'include',
        headers: {
          'Accept': 'application/json',
          // SECURITY: Auth is exclusively via httpOnly cookies.
          // No Bearer token is attached — the cookie is already set by the login response.
          ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
        },
      });

      if (!meResponse.ok) {
        throw new Error('Failed to fetch user data after login');
      }

      const userData = await meResponse.json();
      setUser(userData);
      setIsAuthenticated(true);

      console.log('✅ Login successful:', userData.email);
      return { success: true, user: userData };

    } catch (err) {
      console.error('❌ Login error:', err);
      setError(err.message);
      setIsAuthenticated(false);
      setUser(null);
      return { success: false, error: err.message };
    } finally {
      setIsLoading(false);
    }
  }, []);

  const demoLogin = useCallback(async (role) => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await fetch(`${API_BASE}/auth/demo-login`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ role }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        const detail = typeof body.detail === 'object' ? body.detail.message : body.detail;
        throw new Error(detail || 'Public demo login is unavailable.');
      }
      const meResponse = await apiFetch('/auth/me', { method: 'GET' });
      if (!meResponse.ok) throw new Error('Failed to establish the demo session.');
      const userData = await meResponse.json();
      setUser(userData);
      setIsAuthenticated(true);
      return { success: true, user: userData };
    } catch (err) {
      setError(err.message);
      setUser(null);
      setIsAuthenticated(false);
      return { success: false, error: err.message };
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Logout function
  const logout = useCallback(async () => {
    try {
      // Call backend logout if available
      await apiFetch('/auth/logout', {
        method: 'POST',
        _skipAuthRefresh: true,
      }).catch(() => {
        // Ignore errors from logout endpoint
      });
    } catch (err) {
      console.error('Logout error:', err);
    } finally {
      // Clear all auth state
      setUser(null);
      setIsAuthenticated(false);
      // Legacy cleanup — remove any leftover keys from prior versions
      localStorage.removeItem('finsolve_auth_token');
      localStorage.removeItem('accessToken');
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      console.log('✅ Logged out');
    }
  }, []);

  // Refresh auth state (called on 401 errors)
  const refreshAuth = useCallback(async () => {
    try {
      // SECURITY: refresh_token is httpOnly cookie — we can't read it from JS.
      // Just attempt the refresh; the backend will verify the cookie.
      if (await refreshSession()) {
        console.log('✅ Token refreshed successfully');
        await checkAuth(); // Re-check auth status
        return true;
      }

      // Refresh failed - clear auth
      await logout();
      return false;
    } catch (err) {
      console.error('❌ Refresh auth failed:', err);
      await logout();
      return false;
    }
  }, [checkAuth, logout]);

  // Set up auth error callback for apiClient
  useEffect(() => {
    setAuthErrorCallback(() => {
      console.log('⚠️ Auth error callback triggered - logging out');
      logout();
    });
  }, [logout]);

  // Boot check on mount
  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const value = {
    user,
    isAuthenticated,
    isInitialized,
    isLoading,
    error,
    login,
    demoLogin,
    logout,
    refreshAuth,
    checkAuth,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

export default AuthContext;

