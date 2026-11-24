import React, { useCallback, useLayoutEffect, useRef } from 'react';
import { Send, Square, Loader2 } from 'lucide-react';

const MAX_HEIGHT = 200; // keep in sync with .fs-composer textarea max-height

/**
 * Shared message composer (chat page and home page).
 * - Enter sends, Shift+Enter inserts a newline.
 * - Enter is ignored while an IME (Bangla, etc.) is composing a candidate.
 * - The textarea grows with its content up to MAX_HEIGHT, then scrolls
 *   internally; the composer sits in normal layout flow so it never covers
 *   the transcript.
 * - Optional slots: ``beforeSend`` (e.g. the dictation mic), ``tools`` (a
 *   secondary row: model / thinking effort) and ``status`` (one line below).
 */
export const ChatComposer = ({
  value,
  onChange,
  onSubmit,
  onStop,
  isStreaming = false,
  isLoading = false,
  disabled = false,
  placeholder = 'Ask a question about your documents',
  inputRef,
  autoFocus = false,
  showHint = true,
  id = 'chat-composer',
  beforeSend = null,
  tools = null,
  status = null
}) => {
  const localRef = useRef(null);
  const ref = inputRef || localRef;

  const resize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [ref]);

  // Re-measure whenever the value changes from outside too (prefill, clear).
  useLayoutEffect(resize, [value, resize]);

  const handleKeyDown = (e) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      // While a response streams the owner explains why Enter does nothing.
      onSubmit?.();
    }
  };

  const canSend = value.trim().length > 0 && !isLoading && !disabled;
  const stopMode = isStreaming && !!onStop;

  return (
    <div className="fs-composer-wrap" id={id}>
      <div className="fs-composer-inner">
        <form
          className={`fs-composer${tools ? ' fs-composer--tools' : ''}`}
          onSubmit={(e) => {
            e.preventDefault();
            if (!isStreaming && canSend) onSubmit?.();
          }}
        >
          <div className="fs-composer-row">
          <label htmlFor={`${id}-input`} className="fs-sr-only">
            Message
          </label>
          <textarea
            id={`${id}-input`}
            ref={ref}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            rows={1}
            autoFocus={autoFocus}
            disabled={disabled}
            enterKeyHint="send"
          />
          {beforeSend}
          {stopMode ? (
            <button
              type="button"
              className="fs-send fs-send--stop"
              onClick={onStop}
              aria-label="Stop response"
              title="Stop response"
            >
              <Square size={16} fill="currentColor" aria-hidden="true" />
            </button>
          ) : (
            <button
              type="submit"
              className="fs-send"
              disabled={!canSend}
              aria-label={isLoading ? 'Sending message' : 'Send message'}
              title={canSend ? 'Send message (Enter)' : 'Type a message to send'}
            >
              {isLoading ? <Loader2 size={18} className="fs-spin" aria-hidden="true" /> : <Send size={18} aria-hidden="true" />}
            </button>
          )}
          </div>
          {tools}
        </form>
        {status}
        {showHint && !status && (
          <p className="fs-composer-hint">Enter to send · Shift+Enter for a new line</p>
        )}
      </div>
    </div>
  );
};

export default ChatComposer;
