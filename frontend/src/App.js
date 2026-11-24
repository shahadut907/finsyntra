import React, { useState, useCallback, useRef } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useNavigate, Link } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import LandingPage from './components/LandingPage';
import ChatPage from './components/ChatPage';
import HistoryPage from './components/HistoryPage';
import AdminDashboard from './components/AdminDashboard';
import LoginForm from './components/LoginForm';
import AppShell from './components/layout/AppShell';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { apiFetch } from './lib/apiClient';
import { canAccessAdmin } from './lib/identity';
import useTheme from './hooks/useTheme';
import './App.css';
import './styles/glass.css';
import './styles/admin-glass.css';

// Protected route wrapper
function ProtectedRoute({ children }) {
  const { isAuthenticated, isLoading, isInitialized } = useAuth();

  // CRITICAL: Wait for auth initialization before making redirect decisions
  if (!isInitialized || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center">
          <div className="w-16 h-16 border-4 border-brand border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  console.log('[ProtectedRoute] Auth check:', { isInitialized, isAuthenticated });

  if (!isAuthenticated) {
    console.log('[ProtectedRoute] No auth, redirecting to login');
    return <Navigate to="/login" replace />;
  }

  return children;
}

// Admin-only wrapper: mirrors the backend's admin/c_level check so non-admin
// users land somewhere meaningful instead of a 403 dashboard shell. The role is
// only judged once the session has loaded (ProtectedRoute waits for that), so
// opening or reloading /admin directly does not bounce an admin to Home.
function AdminOnly({ children }) {
  const { user } = useAuth();
  if (!canAccessAdmin(user)) {
    return <Navigate to="/" replace />;
  }
  return children;
}

function AdminRoute({ children }) {
  return (
    <ProtectedRoute>
      <AdminOnly>{children}</AdminOnly>
    </ProtectedRoute>
  );
}

// Placeholder for destinations whose pages are not built yet. Rendered inside
// the app shell so navigation (and the way back) stays available.
function ComingSoon({ title, user, onLogout }) {
  return (
    <AppShell user={user} title={title} onLogout={onLogout}>
      <div className="fs-page-scroll">
        <div className="fs-hero">
          <div className="fs-card" style={{ maxWidth: 440, padding: 32 }}>
            <h2 style={{ margin: '0 0 8px', fontSize: '1.25rem', fontWeight: 600 }}>{title}</h2>
            <p style={{ margin: 0, color: 'var(--fs-text-2)', lineHeight: 1.6 }}>
              This page is not available yet. The rest of FinSyntra works as usual.
            </p>
            <Link to="/chat" className="fs-btn fs-btn--primary" style={{ marginTop: 20, textDecoration: 'none' }}>
              Back to chat
            </Link>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

// Login page wrapper with admin redirect support
function LoginPage() {
  const { login, demoLogin, isLoading, error: authError } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState(null);
  const [showAdminToast, setShowAdminToast] = useState(false);

  const handleLogin = async (credentials) => {
    setError(null);
    setShowAdminToast(false);

    // Extract admin intent (if present)
    const { adminIntent, ...loginCreds } = credentials;

    // Perform normal login (no privilege elevation in request)
    const result = await login(loginCreds);

    if (result.success) {
      // Check if user requested admin access
      if (adminIntent) {
        // Check if user has admin role
        const userRole = result.user?.role?.toLowerCase();
        const userRoles = result.user?.roles || [];
        const isAdmin = userRole === 'admin' ||
          userRole === 'c_level' ||
          userRoles.some(r => r.toLowerCase() === 'admin');

        if (isAdmin) {
          // Redirect to admin dashboard
          navigate('/admin');
        } else {
          // User isn't admin - show toast and redirect to chat
          setShowAdminToast(true);
          setTimeout(() => setShowAdminToast(false), 5000);
          navigate('/chat');
        }
      } else {
        // Normal login flow - redirect to chat
        navigate('/chat');
      }
    } else {
      setError(result.error);
    }
  };

  const handleDemoLogin = async (role) => {
    setError(null);
    const result = await demoLogin(role);
    if (result.success) {
      navigate(role === 'admin' ? '/admin' : '/chat');
    } else {
      setError(result.error);
    }
  };

  return (
    <div className="min-h-screen">
      <LoginForm
        onLogin={handleLogin}
        onDemoLogin={handleDemoLogin}
        isLoading={isLoading}
        error={error || authError}
        darkMode={true}
      />

      {/* Non-blocking toast for non-admin users */}
      {showAdminToast && (
        <div className="fixed top-4 right-4 z-50">
          <div className="px-4 py-3 rounded-lg shadow-lg backdrop-blur-sm bg-yellow-500/90 text-white max-w-sm">
            <p className="text-sm font-medium">Your account doesn't have admin access.</p>
          </div>
        </div>
      )}
    </div>
  );
}

function AppContent() {
  const navigate = useNavigate();
  // Light pearl is the default; the theme is chosen in the sidebar account menu.
  const { theme } = useTheme();
  const darkMode = theme === 'dark';
  const [notifications, setNotifications] = useState([]);
  const { user, logout } = useAuth();

  // API Call Helper with proper auth and path normalization
  const apiCall = useCallback(async (endpoint, options = {}) => {
    // Normalize admin endpoints to use /api prefix
    let normalizedEndpoint = endpoint;
    if (endpoint.startsWith('/admin/') && !endpoint.startsWith('/api/admin/')) {
      normalizedEndpoint = '/api' + endpoint;
    }

    try {
      return await apiFetch(normalizedEndpoint, options);
    } catch (error) {
      console.error('API call error:', error);
      throw error;
    }
  }, []);

  // Glass Toast Notification System
  // Several toasts are often raised in the same millisecond (e.g. upload
  // results); Date.now() ids collided, and the duplicate React keys left
  // orphaned toasts on screen that covered the header actions.
  const toastSeqRef = useRef(0);
  const addNotification = useCallback((message, type = 'info') => {
    toastSeqRef.current += 1;
    const id = toastSeqRef.current;
    // Routine messages leave quickly; errors/warnings stay long enough to read
    // and can be dismissed with the close button.
    const duration = type === 'error' ? 8000 : type === 'warning' ? 6000 : 2500;
    setNotifications(prev => {
      const next = [...prev, { id, message, type, duration, exiting: false }];
      // Keep the stack short so toasts never bury page content: drop the
      // oldest informational toast first, then the oldest non-error. Errors
      // are never dropped to make room.
      const MAX_VISIBLE = 3;
      while (next.length > MAX_VISIBLE) {
        let idx = next.findIndex(n => n.type === 'info');
        if (idx === -1) idx = next.findIndex(n => n.type !== 'error');
        if (idx === -1) break;
        next.splice(idx, 1);
      }
      return next;
    });
    setTimeout(() => {
      // Start exit animation
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, exiting: true } : n));
      // Remove after animation
      setTimeout(() => {
        setNotifications(prev => prev.filter(n => n.id !== id));
      }, 220);
    }, duration);
  }, []);

  const dismissNotification = useCallback((id) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, exiting: true } : n));
    setTimeout(() => {
      setNotifications(prev => prev.filter(n => n.id !== id));
    }, 220);
  }, []);

  const handleLogout = async () => {
    await logout();
    addNotification('Logged out successfully', 'info');
  };

  return (
    <div className={darkMode ? 'dark' : ''}>
      <Routes>
        {/* Login Route */}
        <Route path="/login" element={<LoginPage />} />

        {/* Landing Page Route */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <LandingPage
                user={user}
                onLogout={handleLogout}
                addNotification={addNotification}
              />
            </ProtectedRoute>
          }
        />

        {/* Chat Page Route */}
        <Route
          path="/chat"
          element={
            <ProtectedRoute>
              <ChatPage
                user={user}
                darkMode={darkMode}
                apiCall={apiCall}
                addNotification={addNotification}
                authToken=""
                onLogout={handleLogout}
              />
            </ProtectedRoute>
          }
        />

        {/* History Page Route */}
        <Route
          path="/history"
          element={
            <ProtectedRoute>
              <HistoryPage
                user={user}
                darkMode={darkMode}
                apiCall={apiCall}
                addNotification={addNotification}
                onLogout={handleLogout}
              />
            </ProtectedRoute>
          }
        />

        {/* Admin Dashboard Route */}
        <Route
          path="/admin"
          element={
            <AdminRoute>
              <AdminDashboard
                isOpen={true}
                onClose={() => navigate('/chat')}
                user={user}
                darkMode={darkMode}
                apiCall={apiCall}
                addNotification={addNotification}
                onLogout={handleLogout}
              />
            </AdminRoute>
          }
        />

        {/* Documents Page Route */}
        <Route
          path="/documents"
          element={
            <ProtectedRoute>
              <ComingSoon title="Documents" user={user} onLogout={handleLogout} />
            </ProtectedRoute>
          }
        />

        {/* Search Page Route */}
        <Route
          path="/search"
          element={
            <ProtectedRoute>
              <ComingSoon title="Search" user={user} onLogout={handleLogout} />
            </ProtectedRoute>
          }
        />

        {/* Reports Page Route */}
        <Route
          path="/reports"
          element={
            <ProtectedRoute>
              <ComingSoon title="Reports" user={user} onLogout={handleLogout} />
            </ProtectedRoute>
          }
        />

        {/* Insights Page Route */}
        <Route
          path="/insights"
          element={
            <ProtectedRoute>
              <ComingSoon title="Insights" user={user} onLogout={handleLogout} />
            </ProtectedRoute>
          }
        />

        {/* Performance Page Route */}
        <Route
          path="/performance"
          element={
            <ProtectedRoute>
              <ComingSoon title="Performance" user={user} onLogout={handleLogout} />
            </ProtectedRoute>
          }
        />

        {/* Admin Sub-routes */}
        <Route
          path="/admin/users"
          element={
            <AdminRoute>
              <ComingSoon title="User Management" user={user} onLogout={handleLogout} />
            </AdminRoute>
          }
        />
        <Route
          path="/admin/settings"
          element={
            <AdminRoute>
              <ComingSoon title="Settings" user={user} onLogout={handleLogout} />
            </AdminRoute>
          }
        />
        <Route
          path="/admin/system"
          element={
            <AdminRoute>
              <ComingSoon title="System Status" user={user} onLogout={handleLogout} />
            </AdminRoute>
          }
        />

        {/* Redirect unknown routes to dashboard (stay authenticated) */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      {/* Glass Toast Notifications */}
      <div className="glass-toast-container">
        {notifications.map(notif => {
          const icons = { success: '✓', error: '✗', info: 'ℹ', warning: '⚠' };
          return (
            <div
              key={notif.id}
              className={`glass-toast toast-${notif.type} ${notif.exiting ? 'exiting' : ''}`}
              role={notif.type === 'error' ? 'alert' : 'status'}
              aria-live={notif.type === 'error' ? 'assertive' : 'polite'}
            >
              <span className="glass-toast-icon" aria-hidden="true">
                {icons[notif.type] || icons.info}
              </span>
              <span className="glass-toast-text">{notif.message}</span>
              {(notif.type === 'error' || notif.type === 'warning') && (
                <button
                  type="button"
                  className="glass-toast-close"
                  onClick={() => dismissNotification(notif.id)}
                  aria-label="Dismiss notification"
                >
                  ×
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <Router basename="/app">
        {/* reducedMotion="user": framer-motion skips transform animations when
            the OS asks for reduced motion */}
        <MotionConfig reducedMotion="user">
          <AppContent />
        </MotionConfig>
      </Router>
    </AuthProvider>
  );
}

export default App;
