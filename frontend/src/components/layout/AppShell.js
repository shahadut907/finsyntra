import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Menu } from 'lucide-react';
import Sidebar from './Sidebar';
import { HeaderSlotContext } from './HeaderSlot';
import useMediaQuery from '../../hooks/useMediaQuery';
import useFocusTrap from '../../hooks/useFocusTrap';

const COLLAPSE_KEY = 'finsolve.sidebarCollapsed';

const readCollapsed = () => {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === 'true';
  } catch {
    return false;
  }
};

/**
 * Application shell with explicit regions:
 *   sidebar  — identity, New conversation, navigation, history, account
 *   header   — page / conversation title + page-specific actions (slot)
 *   content  — the page; chat owns its own scroller, composer stays in flow
 * The shell is exactly one viewport tall (100dvh) and never scrolls itself.
 */
export const AppShell = ({
  children,
  user,
  title = 'FinSyntra',
  subtitle,
  onLogout,
  onOpenSettings,
  onNewConversation,
  conversations,
  currentConversationId,
  onSelectConversation,
  onRefreshConversations,
  isLoadingConversations
}) => {
  const location = useLocation();
  const isNarrow = useMediaQuery('(max-width: 899px)');
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [headerSlot, setHeaderSlot] = useState(null);
  const drawerRef = useRef(null);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  const drawerActive = isNarrow && drawerOpen;

  useFocusTrap(drawerActive, drawerRef, closeDrawer);

  // Leaving the narrow layout (rotate / resize) must not leave a stale modal.
  useEffect(() => {
    if (!isNarrow) setDrawerOpen(false);
  }, [isNarrow]);

  // Navigating always dismisses the drawer.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(COLLAPSE_KEY, String(next));
      } catch {
        /* storage unavailable: preference just isn't remembered */
      }
      return next;
    });
  };

  const sidebarProps = {
    user,
    onLogout,
    onOpenSettings,
    onNewConversation,
    conversations,
    currentConversationId,
    onSelectConversation,
    onRefreshConversations,
    isLoadingConversations
  };

  return (
    <HeaderSlotContext.Provider value={headerSlot}>
      <div className="fs-app" data-collapsed={!isNarrow && collapsed ? 'true' : 'false'}>
        <a href="#main-content" className="fs-skip-link">
          Skip to main content
        </a>

        {!isNarrow && (
          <Sidebar {...sidebarProps} collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
        )}

        {drawerActive && (
          <>
            <div className="fs-overlay" onClick={closeDrawer} aria-hidden="true" />
            <div ref={drawerRef} tabIndex={-1}>
              <Sidebar {...sidebarProps} isDrawer onClose={closeDrawer} onNavigate={closeDrawer} />
            </div>
          </>
        )}

        <div className="fs-main">
          <header className="fs-header">
            {isNarrow && (
              <button
                type="button"
                className="fs-btn fs-btn--icon fs-btn--ghost"
                onClick={() => setDrawerOpen(true)}
                aria-label="Open navigation menu"
                aria-haspopup="dialog"
                aria-expanded={drawerActive}
              >
                <Menu size={20} aria-hidden="true" />
              </button>
            )}
            <div className="fs-header-title">
              <h1 title={title}>{title}</h1>
              {subtitle && <p>{subtitle}</p>}
            </div>
            <div className="fs-header-actions" ref={setHeaderSlot} />
          </header>

          <main id="main-content" className="fs-content" tabIndex={-1}>
            {children}
          </main>
        </div>
      </div>
    </HeaderSlotContext.Provider>
  );
};

export default AppShell;
