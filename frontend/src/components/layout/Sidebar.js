import React, { useMemo, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import {
  SquarePen,
  Search,
  Home,
  MessageSquare,
  History,
  BookOpen,
  BarChart3,
  ShieldCheck,
  RefreshCw,
  LogOut,
  Settings,
  Moon,
  Sun,
  PanelLeftClose,
  PanelLeftOpen,
  ChevronsUpDown,
  X
} from 'lucide-react';
import { NAV } from '../../routes';
import { formatDate } from '../../lib/utils';
import { canAccessAdmin, displayName, roleLabel } from '../../lib/identity';
import MenuButton from '../ui/MenuButton';
import useTheme from '../../hooks/useTheme';
import logo from '../../assets/finsyntra-logo.png';

const ICONS = { Home, MessageSquare, History, Search, BookOpen, BarChart3 };

// Destinations that still render a "coming soon" placeholder. They stay in
// the navigation (the routes exist) but say so instead of posing as live.
const PLACEHOLDER_KEYS = new Set(['search', 'docs', 'stats']);

const ADMIN_ITEM = {
  key: 'admin',
  path: '/admin',
  icon: 'Admin',
  label: 'Admin',
  description: 'Admin dashboard: documents, users and system tools'
};

export const Sidebar = ({
  user,
  collapsed = false,
  isDrawer = false,
  onToggleCollapsed,
  onClose,
  onNavigate,
  onNewConversation,
  onLogout,
  onOpenSettings,
  conversations,
  currentConversationId,
  onSelectConversation,
  onRefreshConversations,
  isLoadingConversations = false
}) => {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');
  const { theme, toggleTheme } = useTheme();
  const name = displayName(user);
  const role = roleLabel(user);
  const showHistory = Array.isArray(conversations) && !collapsed;

  const navItems = useMemo(
    () => (canAccessAdmin(user) ? [...NAV, ADMIN_ITEM] : NAV),
    [user]
  );

  const visibleConversations = useMemo(() => {
    if (!Array.isArray(conversations)) return [];
    const term = filter.trim().toLowerCase();
    if (!term) return conversations;
    return conversations.filter((c) =>
      String(c.session_name || c.title || 'Untitled chat').toLowerCase().includes(term)
    );
  }, [conversations, filter]);

  const tip = (label) => (collapsed ? { 'data-tip': label } : {});

  const accountItems = [
    {
      label: theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme',
      icon: theme === 'dark' ? Sun : Moon,
      onSelect: toggleTheme
    },
    {
      label: 'Preferences',
      icon: Settings,
      disabled: true,
      hint: 'Soon',
      onSelect: onOpenSettings
    },
    {
      label: 'Sign out',
      icon: LogOut,
      danger: true,
      separatorBefore: true,
      onSelect: () => {
        onNavigate?.();
        onLogout?.();
      }
    }
  ];

  return (
    <aside
      className={[
        'fs-sidebar',
        collapsed && 'fs-sidebar--collapsed',
        isDrawer && 'fs-sidebar--drawer'
      ].filter(Boolean).join(' ')}
      {...(isDrawer
        ? { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Navigation menu', tabIndex: -1 }
        : { 'aria-label': 'Sidebar' })}
    >
      <div className="fs-sidebar-top">
        <Link to="/" className="fs-brand" onClick={onNavigate} aria-label="FinSyntra AI home">
          <img src={logo} alt="" />
          <span>FinSyntra</span>
        </Link>
        {isDrawer ? (
          <button type="button" className="fs-btn fs-btn--icon fs-btn--ghost" onClick={onClose} aria-label="Close navigation">
            <X size={18} aria-hidden="true" />
          </button>
        ) : (
          <button
            type="button"
            className="fs-btn fs-btn--icon fs-btn--ghost"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-pressed={collapsed}
            {...tip(collapsed ? 'Expand sidebar' : 'Collapse sidebar')}
          >
            {collapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}
          </button>
        )}
      </div>

      <div className="fs-sidebar-body">
        <button
          type="button"
          className="fs-newchat fs-btn--new"
          onClick={() => {
            onNavigate?.();
            if (onNewConversation) {
              onNewConversation();
            } else {
              navigate('/chat', { state: { newConversation: true } });
            }
          }}
          aria-label="New conversation"
          {...tip('New conversation')}
        >
          <SquarePen size={17} aria-hidden="true" />
          <span className="fs-btn-label">New chat</span>
        </button>

        <nav aria-label="Main navigation">
          <ul className="fs-nav">
            {navItems.map((item) => {
              const Icon = ICONS[item.icon] || ShieldCheck;
              const placeholder = PLACEHOLDER_KEYS.has(item.key);
              return (
                <li key={item.key}>
                  <NavLink
                    to={item.path}
                    end
                    onClick={onNavigate}
                    className="fs-nav-item"
                    aria-label={placeholder ? `${item.label} (coming soon)` : item.label}
                    title={collapsed ? undefined : item.description}
                    {...tip(item.label)}
                  >
                    <Icon size={18} aria-hidden="true" />
                    <span className="fs-nav-label">{item.label}</span>
                    {placeholder && <span className="fs-soon">Soon</span>}
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </nav>

        {showHistory && (
          <section className="fs-history-section" aria-label="Recent conversations">
            <h2 className="fs-section-label">
              <span>Recent conversations</span>
              <button
                type="button"
                className="fs-btn fs-btn--icon fs-btn--ghost fs-btn--sm"
                onClick={onRefreshConversations}
                disabled={isLoadingConversations}
                aria-label="Refresh conversation list"
                title="Refresh conversation list"
              >
                <RefreshCw size={14} className={isLoadingConversations ? 'fs-spin' : undefined} aria-hidden="true" />
              </button>
            </h2>
            <label className="fs-field">
              <span className="fs-sr-only">Filter conversations by title</span>
              <Search aria-hidden="true" />
              <input
                type="search"
                className="fs-input"
                placeholder="Filter conversations"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </label>
            <div className="fs-history" role="list">
              {visibleConversations.length === 0 && !isLoadingConversations && (
                <p className="fs-empty-note">
                  {conversations.length === 0
                    ? 'No conversations yet. Start one with New conversation.'
                    : 'No conversations match that filter.'}
                </p>
              )}
              {visibleConversations.map((session) => {
                const title = session.session_name || session.title || 'Untitled chat';
                const updated = session.updated_at || session.created_at;
                const isActive = session.id === currentConversationId;
                return (
                  <div role="listitem" key={session.id}>
                    <button
                      type="button"
                      className="fs-history-item"
                      aria-current={isActive ? 'true' : undefined}
                      onClick={() => {
                        onSelectConversation?.(session.id);
                        onNavigate?.();
                      }}
                    >
                      <span className="fs-history-title">{title}</span>
                      <span className="fs-history-meta">
                        {session.message_count || 0} messages{updated ? ` · ${formatDate(updated)}` : ''}
                      </span>
                    </button>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>

      <div className="fs-account">
        <MenuButton
          label={`Account menu for ${name}`}
          items={accountItems}
          placement="top-start"
          block
          buttonClassName="fs-account-btn"
        >
          <span className="fs-avatar-circle" aria-hidden="true">{name.charAt(0).toUpperCase()}</span>
          <span className="fs-account-text">
            <span className="fs-account-name">{name}</span>
            {role && <span className="fs-role-badge">{role}</span>}
          </span>
          <ChevronsUpDown size={16} aria-hidden="true" className="fs-btn-label" style={{ color: 'var(--fs-text-3)', flex: 'none' }} />
        </MenuButton>
      </div>
    </aside>
  );
};

export default Sidebar;
