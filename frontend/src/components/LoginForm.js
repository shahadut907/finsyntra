import React, { useState } from 'react';
import { Eye, EyeOff, LogIn, User, Lock, Shield, ShieldCheck, Server, Crown } from 'lucide-react';
import { Button } from './ui/Button';
import { Card, CardContent } from './ui/Card';
import { Input, Label } from './ui/Input';
import { cn } from '../lib/utils';
import Logo from './ui/Logo';
import './Login.css';

// Public demo personas — one compact chip each. Visible labels are short;
// aria-labels keep the full "Continue as <Role>" accessible names.
const DEMO_PERSONAS = [
  { role: 'admin', short: 'Admin', label: 'Continue as Admin', Icon: Shield, featured: true },
  { role: 'employee', short: 'Employee', label: 'Continue as Employee', Icon: User },
  { role: 'finance', short: 'Finance', label: 'Continue as Finance', Icon: User },
  { role: 'hr', short: 'HR', label: 'Continue as HR', Icon: User },
  { role: 'engineering', short: 'Engineering', label: 'Continue as Engineering', Icon: User },
  { role: 'ceo', short: 'CEO', label: 'Continue as CEO', Icon: Crown },
];

const LoginForm = ({ onLogin, onDemoLogin, isLoading, error, darkMode }) => {
  const [credentials, setCredentials] = useState({
    username: '',
    password: ''
  });
  const [showPassword, setShowPassword] = useState(false);

  // Admin login checkbox state with localStorage persistence
  const [signInAsAdmin, setSignInAsAdmin] = useState(() => {
    try {
      const stored = localStorage.getItem('finsolve.adminLogin');
      return stored === 'true';
    } catch {
      return false;
    }
  });

  // Check if admin login option should be shown (Create React App uses process.env)
  const showAdminLogin = process.env.REACT_APP_ENABLE_ADMIN_LOGIN === 'true';
  const publicDemoEnabled = process.env.REACT_APP_PUBLIC_DEMO_ENABLED === 'true';
  // The landing "Try Demo" CTA links here with ?demo=1. Read from window (not
  // the router) so this component still renders outside a Router.
  const demoRequested = typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).has('demo');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (credentials.username && credentials.password) {
      // Log admin login intent (dev only)
      if (process.env.NODE_ENV === 'development') {
        console.log('AdminLoginIntent:', signInAsAdmin);
      }

      // Pass admin intent to parent
      onLogin({
        ...credentials,
        adminIntent: signInAsAdmin
      });
    }
  };

  // Handle admin checkbox change with localStorage persistence
  const handleAdminCheckboxChange = (e) => {
    const checked = e.target.checked;
    setSignInAsAdmin(checked);
    try {
      localStorage.setItem('finsolve.adminLogin', String(checked));
    } catch (err) {
      console.warn('Failed to persist admin login preference:', err);
    }
  };

  return (
    <div className="login-container">
      <div className="login-atmosphere" aria-hidden="true" />

      <div className="login-shell">
        {/* Brand lockup above the card, shared with the landing page */}
        <header className="login-brand">
          <Logo
            size={44}
            showText={true}
            className="login-brand-logo [&_img]:brightness-0 [&_img]:invert"
          />
          <p className="login-tagline">Financial intelligence, grounded in your data</p>
        </header>

        <div className="login-card-wrapper">
          <Card variant="elevated" hover={false} className="login-card">
            <CardContent className="login-card-body">
              {/* Card Header */}
              <div className="card-header-text">
                <h2>Welcome back</h2>
                <p>Sign in to access your secure workspace</p>
              </div>

              {/* Error Message */}
              {error && (
                <div className="p-4 mb-4 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-sm" role="alert">
                  {typeof error === 'string' ? error : 'An error occurred. Please try again.'}
                </div>
              )}

              {/* Demo was requested from the landing page but this build has no
                  demo panel: say so instead of showing a bare sign-in form. */}
              {demoRequested && !publicDemoEnabled && (
                <div className="p-4 mb-4 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-sm" role="alert">
                  Demo access is not enabled on this FinSyntra build. Sign in with your own account, or ask your administrator to enable the public demo.
                </div>
              )}

              {/* Compact public-demo persona panel (all six roles) */}
              {publicDemoEnabled && (
                <section className="demo-panel" aria-label="Public demo personas">
                  <div className="demo-panel-head">
                    <span className="demo-panel-label">Explore FinSyntra</span>
                    <span className="demo-panel-hint">No credentials required</span>
                  </div>
                  <div className="demo-grid">
                    {DEMO_PERSONAS.map(({ role, short, label, Icon, featured }) => (
                      <button
                        key={role}
                        type="button"
                        className={cn('persona-btn', featured && 'persona-btn-featured')}
                        disabled={isLoading}
                        aria-label={label}
                        title={label}
                        onClick={() => onDemoLogin?.(role)}
                      >
                        <Icon className="w-3.5 h-3.5" />
                        <span>{short}</span>
                      </button>
                    ))}
                  </div>
                  <p className="demo-note">Admin mutations are disabled in public demo. Private accounts retain normal capabilities.</p>
                </section>
              )}

              <div className="login-divider">or continue with email</div>

              <form onSubmit={handleSubmit} className="login-form">
                {/* Username/Email Field */}
                <div className="space-y-2">
                  <Label htmlFor="email">Email Address</Label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <User className="w-[18px] h-[18px] text-muted-foreground" />
                    </div>
                    <Input
                      id="email"
                      type="email"
                      value={credentials.username}
                      onChange={(e) => setCredentials(prev => ({ ...prev, username: e.target.value }))}
                      className="pl-10"
                      placeholder="name@company.com"
                      required
                      autoComplete="email"
                    />
                  </div>
                </div>

                {/* Password Field */}
                <div className="space-y-2">
                  <Label htmlFor="password">Password</Label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <Lock className="w-[18px] h-[18px] text-muted-foreground" />
                    </div>
                    <Input
                      id="password"
                      type={showPassword ? 'text' : 'password'}
                      value={credentials.password}
                      onChange={(e) => setCredentials(prev => ({ ...prev, password: e.target.value }))}
                      className="pl-10 pr-12"
                      placeholder="••••••••"
                      required
                      autoComplete="current-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
                      aria-label={showPassword ? 'Hide input' : 'Show input'}
                    >
                      {showPassword ? (
                        <EyeOff className="w-5 h-5" />
                      ) : (
                        <Eye className="w-5 h-5" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Admin Login Checkbox (conditional) */}
                {showAdminLogin && (
                  <div className="flex items-center space-x-2">
                    <div className="relative flex items-center">
                      <input
                        type="checkbox"
                        id="admin-login"
                        checked={signInAsAdmin}
                        onChange={handleAdminCheckboxChange}
                        aria-label="Sign in as admin"
                      />
                    </div>
                    <label
                      htmlFor="admin-login"
                      className="flex items-center space-x-2 cursor-pointer select-none"
                      title="Access admin dashboard if your account has admin privileges"
                    >
                      <Shield className="w-4 h-4 text-muted-foreground" />
                      <span>Sign in as admin</span>
                    </label>
                  </div>
                )}

                {/* Login Button */}
                <Button
                  type="submit"
                  variant="brand"
                  size="lg"
                  className="login-submit w-full"
                  disabled={isLoading || !credentials.username || !credentials.password}
                  loading={isLoading}
                >
                  {!isLoading && <LogIn className="w-[18px] h-[18px] mr-2" />}
                  {isLoading ? 'Signing In...' : 'Sign In'}
                </Button>
              </form>

              {/* Trust Badges — factual product properties only */}
              <div className="security-badges">
                <div className="security-badge">
                  <ShieldCheck className="badge-icon" />
                  <span>Role-based access control</span>
                </div>
                <div className="security-badge">
                  <Server className="badge-icon" />
                  <span>Tenant-isolated workspaces</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Page Footer */}
          <footer className="login-footer">
            <p>© 2026 FinSyntra AI. Grounded, role-scoped answers.</p>
          </footer>
        </div>
      </div>
    </div>
  );
};

export default LoginForm;
