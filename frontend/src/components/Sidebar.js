import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Home, MessageSquare, Users, BarChart3, Settings, Menu, X,
  Search, Calendar, Bell, BellOff, StickyNote, Download, Wifi, WifiOff, Lock, Unlock,
  Type, Palette, Globe, Eye, EyeOff, Trash2, Edit,
  CheckSquare, BookOpen, HelpCircle, UserPlus, Settings2, FileDown,
  RotateCcw, AlertTriangle, CheckCircle, TrendingUp, Zap, Target, Brain,
  Pin, PinOff, MoreVertical, Filter, SortAsc, Hash, Tag, Layers, Grid,
  ChevronLeft, Sun, Moon, Info, LogOut
} from 'lucide-react';
import { cn, hasPermission } from '../lib/utils';
import { Card, CardHeader, CardTitle, CardContent } from './ui';
import Logo from './ui/Logo';
import NotificationsWidget from './widgets/NotificationsWidget';
import ScratchpadWidget from './widgets/ScratchpadWidget';
import StatusWidget from './widgets/StatusWidget';

const Sidebar = ({
  collapsed,
  onToggleCollapsed,
  user,
  darkMode,
  onToggleTheme,
  onLogout,
  apiCall,
  addNotification,
  backendOnline,
  isAdmin
}) => {
  const navigate = useNavigate();
  const location = useLocation();

  // Derive active section from current route instead of local state
  const getActiveSection = () => {
    const path = location.pathname;
    if (path === '/') return 'dashboard';
    if (path.startsWith('/admin/')) return path.split('/')[2] || 'users';
    return path.split('/')[1] || 'dashboard';
  };
  const activeSection = getActiveSection();
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedGroups, setExpandedGroups] = useState({
    main: true,
    analytics: true,
    admin: isAdmin
  });

  // Listen for keyboard shortcuts
  useEffect(() => {
    const handleKeyboard = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        onToggleCollapsed();
      }
    };

    document.addEventListener('keydown', handleKeyboard);
    return () => document.removeEventListener('keydown', handleKeyboard);
  }, [onToggleCollapsed]);

  const navigationGroups = {
    main: {
      title: 'Main',
      items: [
        { id: 'dashboard', label: 'Dashboard', icon: Home, href: '/' },
        { id: 'chat', label: 'AI Assistant', icon: MessageSquare, href: '/chat' },
        { id: 'documents', label: 'Documents', icon: BookOpen, href: '/documents' },
        { id: 'search', label: 'Search', icon: Search, href: '/search' }
      ]
    },
    analytics: {
      title: 'Analytics',
      items: [
        { id: 'reports', label: 'Reports', icon: BarChart3, href: '/reports' },
        { id: 'insights', label: 'Insights', icon: Brain, href: '/insights' },
        { id: 'performance', label: 'Performance', icon: TrendingUp, href: '/performance' }
      ]
    },
    admin: {
      title: 'Administration',
      items: [
        { id: 'users', label: 'Users', icon: Users, href: '/admin/users' },
        { id: 'settings', label: 'Settings', icon: Settings, href: '/admin/settings' },
        { id: 'system', label: 'System Status', icon: Zap, href: '/admin/system' }
      ],
      adminOnly: true
    }
  };

  const renderNavItem = (item) => (
    <div
      key={item.id}
      onClick={() => navigate(item.href)}
      className={cn(
        "flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-all duration-200",
        "hover:bg-accent hover:text-accent-foreground",
        activeSection === item.id && "bg-primary text-primary-foreground",
        collapsed && "justify-center px-2"
      )}
    >
      <item.icon size={20} />
      {!collapsed && <span className="text-sm font-medium">{item.label}</span>}
    </div>
  );

  const renderNavGroup = (groupId, group) => {
    if (group.adminOnly && !isAdmin) return null;

    return (
      <div key={groupId} className="space-y-2">
        {!collapsed && (
          <div className="flex items-center justify-between px-3 py-1">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              {group.title}
            </h3>
            <button
              onClick={() => setExpandedGroups(prev => ({ ...prev, [groupId]: !prev[groupId] }))}
              className="p-1 hover:bg-accent rounded"
            >
              <ChevronLeft
                size={14}
                className={cn(
                  "transition-transform duration-200",
                  expandedGroups[groupId] && "rotate-[-90deg]"
                )}
              />
            </button>
          </div>
        )}
        {(collapsed || expandedGroups[groupId]) && (
          <div className="space-y-1">
            {group.items.map(renderNavItem)}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={cn(
      "sidebar-container h-full bg-card border-r border-border",
      "flex flex-col transition-all duration-300 ease-in-out",
      collapsed ? "w-16" : "w-72"
    )}>
      {/* Sidebar Header */}
      <div className="sidebar-header p-4 border-b border-border">
        <div className="flex items-center justify-between">
          {!collapsed ? (
            <Logo size={36} showText={true} className="[&_img]:brightness-0 [&_img]:invert [&_span]:!text-white" />
          ) : (
            <Logo size={28} showText={false} className="[&_img]:brightness-0 [&_img]:invert" />
          )}
          <button
            onClick={onToggleCollapsed}
            className="p-2 hover:bg-accent rounded-lg transition-colors"
            title={collapsed ? "Expand Sidebar" : "Collapse Sidebar"}
          >
            {collapsed ? <Menu size={20} /> : <X size={16} />}
          </button>
        </div>
      </div>

      {/* User Info */}
      {!collapsed && (
        <div className="p-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-accent rounded-full flex items-center justify-center">
              <span className="text-sm font-semibold">
                {user?.name?.charAt(0) || 'U'}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{user?.name || 'User'}</p>
              <p className="text-xs text-muted-foreground capitalize">
                {user?.role || 'Employee'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Sidebar Content */}
      <div className="sidebar-content flex-1 overflow-y-auto p-4 space-y-6">
        {/* Navigation Search */}
        {!collapsed && (
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search navigation..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm bg-accent border-0 rounded-lg focus:ring-2 focus:ring-primary focus:outline-none"
            />
          </div>
        )}

        {/* Navigation Groups */}
        <div className="space-y-6">
          {Object.entries(navigationGroups).map(([groupId, group]) =>
            renderNavGroup(groupId, group)
          )}
        </div>

        {/* Productivity Widgets */}
        {!collapsed && (
          <div className="space-y-4">
            <ScratchpadWidget
              apiCall={apiCall}
              addNotification={addNotification}
              backendOnline={backendOnline}
            />

            <NotificationsWidget
              apiCall={apiCall}
              backendOnline={backendOnline}
            />

            {/* Only show admin widgets for admin users */}
            {isAdmin && (
              <StatusWidget
                apiCall={apiCall}
                backendOnline={backendOnline}
              />
            )}
          </div>
        )}
      </div>

      {/* Sidebar Footer */}
      <div className="sidebar-footer p-4 border-t border-border">
        <div className="space-y-2">
          {/* Download Chat (PDF) */}
          <button
            onClick={() => {
              if (typeof window === 'undefined') return;
              // Ask the chat view to export current conversation
              window.dispatchEvent(new CustomEvent('finsolve:download-pdf'));
            }}
            className={cn(
              "w-full flex items-center gap-3 px-3 py-2 rounded-lg",
              "hover:bg-accent hover:text-accent-foreground transition-colors",
              collapsed && "justify-center px-2"
            )}
            title="Download Chat (PDF)"
          >
            <FileDown size={20} />
            {!collapsed && <span className="text-sm">Download Chat (PDF)</span>}
          </button>

          {/* Theme Toggle */}
          <button
            onClick={onToggleTheme}
            className={cn(
              "w-full flex items-center gap-3 px-3 py-2 rounded-lg",
              "hover:bg-accent hover:text-accent-foreground transition-colors",
              collapsed && "justify-center px-2"
            )}
            title={darkMode ? "Switch to Light Mode" : "Switch to Dark Mode"}
          >
            {darkMode ? <Sun size={20} /> : <Moon size={20} />}
            {!collapsed && (
              <span className="text-sm">{darkMode ? 'Light Mode' : 'Dark Mode'}</span>
            )}
          </button>

          {/* Logout */}
          <button
            onClick={onLogout}
            className={cn(
              "w-full flex items-center gap-3 px-3 py-2 rounded-lg",
              "hover:bg-destructive hover:text-destructive-foreground transition-colors",
              collapsed && "justify-center px-2"
            )}
            title="Logout"
          >
            <LogOut size={20} />
            {!collapsed && <span className="text-sm">Logout</span>}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Sidebar;
