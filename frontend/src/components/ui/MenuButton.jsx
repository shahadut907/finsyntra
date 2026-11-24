import React, { useCallback, useEffect, useId, useRef, useState } from 'react';

/**
 * Accessible popover menu. The trigger is a real button (aria-haspopup,
 * aria-expanded); the panel is role="menu" with arrow-key navigation,
 * Escape-to-close with focus return, and outside-click dismissal.
 *
 * items: [{ label, icon: Icon, onSelect, disabled, hint, danger, separatorBefore,
 *           description, checked }]
 * An item with a boolean ``checked`` renders as role="menuitemradio" with
 * aria-checked, for single-choice menus such as the model picker.
 */
export default function MenuButton({
  label,
  items,
  placement = 'bottom-end',
  buttonClassName = 'fs-btn fs-btn--icon fs-btn--ghost',
  block = false,
  buttonTitle,
  menuClassName = '',
  disabled = false,
  children
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const buttonRef = useRef(null);
  const menuRef = useRef(null);
  const menuId = useId();

  const close = useCallback((returnFocus = true) => {
    setOpen(false);
    if (returnFocus) buttonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('touchstart', onPointerDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('touchstart', onPointerDown);
    };
  }, [open]);

  useEffect(() => {
    if (open) {
      const first =
        menuRef.current?.querySelector('[role^="menuitem"][aria-checked="true"]:not([aria-disabled="true"])') ||
        menuRef.current?.querySelector('[role^="menuitem"]:not([aria-disabled="true"])') ||
        menuRef.current?.querySelector('[role^="menuitem"]');
      first?.focus();
    }
  }, [open]);

  const onMenuKeyDown = (event) => {
    const nodes = Array.from(menuRef.current?.querySelectorAll('[role^="menuitem"]') || []);
    const index = nodes.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      nodes[(index + 1) % nodes.length]?.focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      nodes[(index - 1 + nodes.length) % nodes.length]?.focus();
    } else if (event.key === 'Home') {
      event.preventDefault();
      nodes[0]?.focus();
    } else if (event.key === 'End') {
      event.preventDefault();
      nodes[nodes.length - 1]?.focus();
    } else if (event.key === 'Tab') {
      setOpen(false);
    }
  };

  const onTriggerKeyDown = (event) => {
    if (event.key === 'ArrowDown' && !open) {
      event.preventDefault();
      setOpen(true);
    }
  };

  const select = (item) => {
    if (item.disabled) return;
    // Return focus to the trigger (menu-button pattern) before acting, so an
    // action that moves focus itself (dialog, navigation) still wins.
    close(true);
    item.onSelect?.();
  };

  return (
    <div ref={rootRef} className={`fs-menu-root${block ? ' fs-menu-root--block' : ''}`}>
      <button
        ref={buttonRef}
        type="button"
        className={buttonClassName}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        title={buttonTitle}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onTriggerKeyDown}
      >
        {children}
      </button>
      {open && (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={label}
          className={`fs-menu fs-menu--${placement}${menuClassName ? ` ${menuClassName}` : ''}`}
          onKeyDown={onMenuKeyDown}
        >
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <React.Fragment key={item.label}>
                {item.separatorBefore && <div className="fs-menu-sep" role="separator" />}
                {item.heading && (
                  <div className="fs-menu-heading" role="presentation">{item.heading}</div>
                )}
                <button
                  type="button"
                  role={typeof item.checked === 'boolean' ? 'menuitemradio' : 'menuitem'}
                  aria-checked={typeof item.checked === 'boolean' ? String(item.checked) : undefined}
                  aria-disabled={item.disabled ? 'true' : undefined}
                  aria-busy={item.busy ? 'true' : undefined}
                  aria-label={item.ariaLabel}
                  title={item.title}
                  className={`fs-menu-item${item.danger ? ' fs-menu-item--danger' : ''}${item.description ? ' fs-menu-item--rich' : ''}`}
                  onClick={() => select(item)}
                >
                  {Icon && <Icon size={16} aria-hidden="true" />}
                  {item.description ? (
                    <span className="fs-menu-text">
                      <span>{item.label}</span>
                      <span className="fs-menu-desc">{item.description}</span>
                    </span>
                  ) : (
                    <span>{item.label}</span>
                  )}
                  {item.hint && <span className="fs-menu-hint">{item.hint}</span>}
                  {item.checked && <span className="fs-menu-check" aria-hidden="true">✓</span>}
                </button>
              </React.Fragment>
            );
          })}
        </div>
      )}
    </div>
  );
}
