import React, { useState, useEffect } from 'react';
import { Settings, Bell, Menu, X, User } from 'lucide-react';
import Sidebar from './Sidebar';

const AppShell = ({ 
  children, 
  user, 
  darkMode, 
  onToggleTheme, 
  onLogout, 
  apiCall, 
  addNotification 
}) => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [backendOnline, setBackendOnline] = useState(true);

  // Fix: Backend health check with stable reference
  const checkBackendHealth = React.useCallback(async () => {
    try {
      await apiCall('/health');
      setBackendOnline(true);
    } catch (error) {
      setBackendOnline(false);
    }
  }, [apiCall]);

  useEffect(() => {
    checkBackendHealth();
    const interval = setInterval(checkBackendHealth, 30000); // Check every 30 seconds
    return () => clearInterval(interval);
  }, [checkBackendHealth]);

  const toggleSidebar = () => {
    setSidebarCollapsed(!sidebarCollapsed);
  };

  const handleKeyboardShortcuts = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
      e.preventDefault();
      toggleSidebar();
    }
  };

  useEffect(() => {
    document.addEventListener('keydown', handleKeyboardShortcuts);
    return () => document.removeEventListener('keydown', handleKeyboardShortcuts);
  }, []);

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <div className={`${sidebarCollapsed ? 'w-16' : 'w-80'} transition-all duration-300 ease-in-out`}>
        <Sidebar
          collapsed={sidebarCollapsed}
          onToggleCollapsed={toggleSidebar}
          user={user}
          darkMode={darkMode}
          onToggleTheme={onToggleTheme}
          onLogout={onLogout}
          apiCall={apiCall}
          addNotification={addNotification}
          backendOnline={backendOnline}
          isAdmin={user?.role === 'admin' || user?.is_admin}
        />
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <header className="h-16 border-b bg-card flex items-center justify-between px-6">
          <div className="flex items-center gap-4">
            <button
              onClick={toggleSidebar}
              className="p-2 hover:bg-accent hover:text-accent-foreground rounded-md transition-colors"
              title="Toggle Sidebar (Ctrl+B)"
            >
              <Menu size={20} />
            </button>
            
            {!backendOnline && (
              <div className="flex items-center gap-2 text-red-600">
                <div className="w-2 h-2 bg-red-500 rounded-full"></div>
                Backend Offline
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>{user?.name || 'User'}</span>
              <span className="text-xs bg-muted px-2 py-1 rounded">
                {user?.role || 'employee'}
              </span>
            </div>
            
            <button
              onClick={() => setShowSettings(true)}
              className="p-2 hover:bg-accent hover:text-accent-foreground rounded-md transition-colors"
              title="Settings"
            >
              <Settings size={20} />
            </button>
          </div>
        </header>

        {/* Main Content Area */}
        <main className="flex-1 overflow-hidden">
          {children}
        </main>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-lg p-6 max-w-md w-full mx-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Settings</h2>
              <button
                onClick={() => setShowSettings(false)}
                className="p-1 hover:bg-accent rounded"
              >
                <X size={16} />
              </button>
            </div>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span>Dark Mode</span>
                <button
                  onClick={onToggleTheme}
                  className="p-2 bg-accent rounded"
                >
                  {darkMode ? 'Light' : 'Dark'}
                </button>
              </div>
              <div className="flex items-center justify-between">
                <span>Backend Status</span>
                <span className={backendOnline ? 'text-green-600' : 'text-red-600'}>
                  {backendOnline ? 'Online' : 'Offline'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>User Role</span>
                <span className="text-sm text-muted-foreground">
                  {user?.role || 'Employee'}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AppShell;
