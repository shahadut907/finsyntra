import { useEffect, useRef } from 'react';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

let idCounter = 0;

/**
 * Modal behaviour for overlay dialogs that are plain markup (the admin
 * dashboard's dialogs are defined as nested components that remount on every
 * render, so a ref-based trap cannot hold). While `active`:
 *  - every overlay matching `selector` is exposed as role="dialog" aria-modal,
 *    labelled by its first heading;
 *  - focus moves into the topmost dialog, Tab/Shift+Tab stay inside it;
 *  - Escape calls `onEscape` (latest closure, via ref);
 *  - focus returns to the previously focused element when the last dialog closes.
 */
export default function useModalDialogs({ active, onEscape, selector = '.glass-modal-overlay' }) {
  const escapeRef = useRef(onEscape);
  escapeRef.current = onEscape;

  // Semantics must be re-applied after any render, since dialogs remount.
  useEffect(() => {
    document.querySelectorAll(selector).forEach((el) => {
      if (el.getAttribute('role') === 'dialog') return;
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-modal', 'true');
      const heading = el.querySelector('h1, h2, h3');
      if (heading) {
        if (!heading.id) {
          idCounter += 1;
          heading.id = `modal-title-${idCounter}`;
        }
        el.setAttribute('aria-labelledby', heading.id);
      }
    });
  });

  useEffect(() => {
    if (!active) return undefined;
    const previouslyFocused = document.activeElement;
    const topDialog = () => {
      const all = document.querySelectorAll(selector);
      return all[all.length - 1] || null;
    };

    const focusInto = () => {
      const dialog = topDialog();
      if (dialog && !dialog.contains(document.activeElement)) {
        const first = dialog.querySelector(FOCUSABLE);
        (first || dialog).focus?.();
      }
    };
    const raf = window.requestAnimationFrame(focusInto);

    const onKeyDown = (event) => {
      const dialog = topDialog();
      if (!dialog) return;
      if (event.key === 'Escape') {
        event.stopPropagation();
        escapeRef.current?.();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = Array.from(dialog.querySelectorAll(FOCUSABLE));
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const head = items[0];
      const tail = items[items.length - 1];
      if (!dialog.contains(document.activeElement)) {
        event.preventDefault();
        head.focus();
      } else if (event.shiftKey && document.activeElement === head) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && document.activeElement === tail) {
        event.preventDefault();
        head.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      window.cancelAnimationFrame(raf);
      document.removeEventListener('keydown', onKeyDown, true);
      if (previouslyFocused && document.contains(previouslyFocused) && previouslyFocused.focus) {
        previouslyFocused.focus();
      }
    };
  }, [active, selector]);
}
