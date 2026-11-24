import { useEffect } from 'react';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal focus management: moves focus into `containerRef` when `active`,
 * keeps Tab/Shift+Tab inside it, closes on Escape, and returns focus to the
 * element that had it before the modal opened.
 */
export default function useFocusTrap(active, containerRef, onClose) {
  useEffect(() => {
    if (!active) return undefined;
    const container = containerRef.current;
    if (!container) return undefined;

    const previouslyFocused = document.activeElement;
    // Skip anything hidden (display:none / visibility:hidden / [hidden]).
    // Computed style rather than offsetParent so it also holds under jsdom.
    const isVisible = (el) => {
      if (el.closest('[hidden]')) return false;
      const style = window.getComputedStyle(el);
      return style.display !== 'none' && style.visibility !== 'hidden';
    };
    const focusables = () =>
      Array.from(container.querySelectorAll(FOCUSABLE)).filter(isVisible);

    const first = focusables()[0];
    (first || container).focus();

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        // An open popover menu handles its own Escape first.
        if (event.target?.closest?.('[role="menu"]')) return;
        event.stopPropagation();
        onClose?.();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const head = items[0];
      const tail = items[items.length - 1];
      if (event.shiftKey && document.activeElement === head) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && document.activeElement === tail) {
        event.preventDefault();
        head.focus();
      } else if (!container.contains(document.activeElement)) {
        event.preventDefault();
        head.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      if (previouslyFocused && typeof previouslyFocused.focus === 'function' && document.contains(previouslyFocused)) {
        previouslyFocused.focus();
      }
    };
    // onClose intentionally excluded: callers pass inline closures and the
    // trap must not re-run (and steal focus) on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, containerRef]);
}
