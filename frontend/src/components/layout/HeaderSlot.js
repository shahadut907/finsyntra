import { createContext, useContext } from 'react';
import { createPortal } from 'react-dom';

/**
 * AppShell owns the header; pages that know about conversation-specific
 * actions (PDF export, ...) render them into it through this portal slot so
 * the actions sit in the header instead of floating over the content.
 */
export const HeaderSlotContext = createContext(null);

export function HeaderActions({ children }) {
  const slot = useContext(HeaderSlotContext);
  return slot ? createPortal(children, slot) : null;
}
