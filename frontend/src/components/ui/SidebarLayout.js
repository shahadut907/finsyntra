import React, { useState, useEffect } from 'react';
import { cn } from '../../lib/utils';
import Sidebar from '../Sidebar';

const SidebarLayout = ({ 
  user, 
  darkMode, 
  onToggleTheme, 
  onLogout, 
  apiCall, 
  addNotification, 
  children,
  className 
}) => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    const saved = localStorage.getItem('finsolve-sidebar-collapsed');
    return saved ? JSON.parse(saved) : false;
  });

  // Listen to sidebar state changes
  useEffect(() => {
    const handleStorageChange = () => {
      const saved = localStorage.getItem('finsolve-sidebar-collapsed');
      setSidebarCollapsed(saved ? JSON.parse(saved) : false);
    };

    window.addEventListener('storage', handleStorageChange);
    
    // Also listen to direct state changes
    const interval = setInterval(handleStorageChange, 100);
    
    return () => {
      window.removeEventListener('storage', handleStorageChange);
      clearInterval(interval);
    };
  }, []);

  return (
    <div className={cn("flex h-screen bg-background", className)}>
      {/* Sidebar */}
      <Sidebar
        user={user}
        darkMode={darkMode}
        onToggleTheme={onToggleTheme}
        onLogout={onLogout}
        apiCall={apiCall}
        addNotification={addNotification}
      />
      
      {/* Main Content */}
      <div 
        className={cn(
          "flex-1 transition-all duration-300",
          sidebarCollapsed ? "ml-[72px]" : "ml-[280px]"
        )}
      >
        {children}
      </div>
    </div>
  );
};

export default SidebarLayout;
