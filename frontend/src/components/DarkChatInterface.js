import React, { useState, useEffect, useRef, useCallback, useLayoutEffect } from 'react';
import { ArrowDown, MoreHorizontal, FileDown, MicOff } from 'lucide-react';
import ChatWelcome from './chat/ChatWelcome';
import ChatMessage, { ThinkingMessage } from './chat/ChatMessage';
import ChatComposer from './chat/ChatComposer';
import { ComposerTools, DictationButton, ComposerStatus } from './chat/ComposerControls';
import useModelCatalog from '../hooks/useModelCatalog';
import useDictation from '../hooks/useDictation';
import MenuButton from './ui/MenuButton';
import { HeaderActions } from './layout/HeaderSlot';
import { NetworkStatus } from './ui/ErrorChip';
import { useChat } from '../hooks/useChat';
import { initializeHealthCheck } from '../lib/health';
import { exportChatToPdf } from '../lib/exportPdf';
import { displayName } from '../lib/identity';

// How close to the bottom (px) still counts as "reading the latest message".
const STICK_THRESHOLD = 96;

const DarkChatInterface = ({
  user,
  apiCall,
  addNotification,
  authToken,
  conversationId,
  ensureConversationId,
  initialPrompt,
  onConversationActivity
}) => {
  const {
    messages,
    sendMessage,
    retryMessage,
    isLoading,
    isStreaming,
    abortStreaming
  } = useChat(apiCall, addNotification, { conversationId, ensureConversationId });

  const [inputValue, setInputValue] = useState('');
  const [showJump, setShowJump] = useState(false);
  const [exporting, setExporting] = useState(false);
  const exportingRef = useRef(false);

  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const stickRef = useRef(true);

  // Model + thinking effort (server catalog; re-validated per request).
  const modelCatalog = useModelCatalog();
  const { sendParams } = modelCatalog;

  // Voice dictation: speech -> editable composer text, never auto-sent.
  const [dictationLanguage, setDictationLanguage] = useState(() => {
    try { return window.localStorage.getItem('finsolve.dictationLanguage') || 'auto'; } catch { return 'auto'; }
  });
  const [pendingConsent, setPendingConsent] = useState(false);
  const dictationInfo = modelCatalog.dictation;
  // Server capability decides availability; an unsupported browser still gets
  // the button so a click can explain why it cannot record.
  const dictationAvailable = Boolean(dictationInfo?.available);
  const appendTranscript = useCallback((text) => {
    // Typed text is preserved; the transcript is appended for review.
    setInputValue((prev) => (prev && !/\s$/.test(prev) ? `${prev} ${text}` : `${prev}${text}`));
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });
  }, []);
  const dictation = useDictation({
    onTranscript: appendTranscript,
    maxSeconds: dictationInfo?.max_seconds || 60,
    language: dictationLanguage,
  });
  const requestDictation = () => {
    let consented = false;
    try { consented = window.localStorage.getItem('finsolve.dictationConsent') === '1'; } catch { /* ignore */ }
    if (consented) dictation.start();
    else setPendingConsent(true);
  };
  const acceptDictation = () => {
    try { window.localStorage.setItem('finsolve.dictationConsent', '1'); } catch { /* ignore */ }
    setPendingConsent(false);
    dictation.start();
  };
  const chooseDictationLanguage = (id) => {
    setDictationLanguage(id);
    try { window.localStorage.setItem('finsolve.dictationLanguage', id); } catch { /* ignore */ }
  };

  // Pre-fill the composer when navigated here with a prompt (e.g. a home-page
  // category pill). Consumed once so refresh/back does not re-insert it.
  useEffect(() => {
    if (initialPrompt) {
      setInputValue(initialPrompt);
      inputRef.current?.focus();
      window.history?.replaceState?.({}, '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const cleanup = initializeHealthCheck();
    return cleanup;
  }, []);

  const scrollToBottom = useCallback((smooth = false) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  }, []);

  // Switching conversations always lands on the latest message.
  useEffect(() => {
    stickRef.current = true;
    setShowJump(false);
  }, [conversationId]);

  // Follow new content only while the reader is already at the bottom — never
  // fight someone scrolling back through the transcript.
  useLayoutEffect(() => {
    if (messages.length === 0) {
      // The welcome screen reads top-down.
      if (scrollRef.current) scrollRef.current.scrollTop = 0;
      return;
    }
    if (stickRef.current) scrollToBottom();
  }, [messages, scrollToBottom]);

  // Keep the bottom pinned when the viewport or composer changes size.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => {
      if (stickRef.current && scrollRef.current?.querySelector('.fs-thread')) scrollToBottom();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [scrollToBottom]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD;
    stickRef.current = near;
    setShowJump(!near);
  };

  const handleSendMessage = async () => {
    if (!inputValue.trim()) return;
    // Enter during an active stream would silently abort the running answer;
    // make that an explicit Stop instead.
    if (isStreaming) {
      addNotification('Stop the current response first, or wait for it to finish.', 'info');
      return;
    }

    const messageText = inputValue;
    setInputValue('');
    stickRef.current = true;
    setShowJump(false);

    try {
      await sendMessage(messageText, {
        ...sendParams,
        // The server refused the chosen model (e.g. it was withdrawn after the
        // picker loaded): reload the catalog so the picker reflects reality.
        // The message is not resent on another model.
        onError: (err) => {
          if (err?.code === 'MODEL_UNAVAILABLE' || err?.code === 'INVALID_EFFORT') modelCatalog.refresh();
        },
      });
      onConversationActivity?.();
    } catch (error) {
      // Error handling is done in the useChat hook
      console.error('Send message error:', error);
    }
  };

  const handleQuickPromptSelect = (promptText) => {
    setInputValue(promptText);
    inputRef.current?.focus();
  };

  const handleDownloadPdf = async () => {
    // Guard against duplicate requests while one export is running.
    if (exportingRef.current) return;
    const exportable = (messages || []).filter(m => !m.isWelcome);
    if (exportable.length === 0) {
      addNotification('No messages to export', 'warning');
      return;
    }

    exportingRef.current = true;
    setExporting(true);
    addNotification('Choose "Save as PDF" in the print dialog', 'info');
    try {
      // Let the notice paint before the print dialog takes over.
      await new Promise((resolve) => setTimeout(resolve, 50));
      await exportChatToPdf({
        messages: exportable,
        fileName: 'finsyntra-chat',
        currentUserName: user?.name || 'User',
        tenant: user?.organization_name || 'FinSyntra Technologies',
        department: user?.department || 'General'
      });
    } catch (error) {
      console.error('PDF export error:', error);
      addNotification('Failed to export PDF', 'error');
    } finally {
      exportingRef.current = false;
      setExporting(false);
    }
  };

  const statusActive = pendingConsent || Boolean(dictation.error) || Boolean(modelCatalog.notice)
    || dictation.state === 'recording' || dictation.state === 'transcribing';

  // Retry with the selection the user currently sees.
  const handleRetry = useCallback(() => retryMessage(sendParams), [retryMessage, sendParams]);

  const hasMessages = Array.isArray(messages) && messages.length > 0;
  const userInitial = (displayName(user) || 'U').charAt(0).toUpperCase();

  // Hide empty assistant messages that are still streaming; the standalone
  // thinking indicator covers that state.
  const visibleMessages = messages.filter(
    (msg) => !(msg.sender === 'assistant' && msg.isStreaming && !msg.text?.trim())
  );
  const thinking = isStreaming && messages.some(m => m.sender === 'assistant' && m.isStreaming && !m.text?.trim());

  const exportable = hasMessages && messages.some(m => !m.isWelcome);
  const overflowItems = [
    {
      heading: 'Export',
      label: exporting ? 'PDF — preparing…' : 'PDF',
      ariaLabel: exporting ? 'Export conversation as PDF, preparing' : 'Export conversation as PDF',
      title: exportable ? undefined : 'Send a message to enable export',
      icon: FileDown,
      disabled: !exportable || exporting,
      busy: exporting,
      hint: exportable ? undefined : 'No messages',
      onSelect: handleDownloadPdf
    }
  ];

  return (
    <div className="fs-chat">
      <NetworkStatus />

      {/* Conversation-specific actions live in the page header, apart from
          the account controls in the sidebar. */}
      <HeaderActions>
        <MenuButton label="Conversation actions" items={overflowItems} placement="bottom-end">
          <MoreHorizontal size={18} aria-hidden="true" />
        </MenuButton>
      </HeaderActions>

      <div className="fs-scroll-wrap">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="fs-scroll"
          tabIndex={0}
          role="region"
          aria-label="Conversation"
        >
          {!hasMessages ? (
            <ChatWelcome user={user} onPromptSelect={handleQuickPromptSelect} />
          ) : (
            <div className="fs-thread">
              {visibleMessages.map((message) => (
                <ChatMessage
                  key={message.id}
                  message={message}
                  userInitial={userInitial}
                  onRetry={handleRetry}
                />
              ))}
              {thinking && (
                <ThinkingMessage statusText={messages.find(m => m.isStreaming)?.statusText} />
              )}
            </div>
          )}
        </div>

        {showJump && hasMessages && (
          <button
            type="button"
            className="fs-btn fs-jump"
            onClick={() => {
              stickRef.current = true;
              setShowJump(false);
              scrollToBottom(true);
            }}
          >
            <ArrowDown size={16} aria-hidden="true" />
            Jump to latest
          </button>
        )}
      </div>

      <div className="fs-sr-only" role="status" aria-live="polite">
        {isStreaming ? 'FinSyntra AI is responding' : ''}
      </div>

      <ChatComposer
        value={inputValue}
        onChange={setInputValue}
        onSubmit={handleSendMessage}
        onStop={abortStreaming}
        isStreaming={isStreaming}
        isLoading={isLoading && !isStreaming}
        inputRef={inputRef}
        placeholder="Ask about your documents"
        beforeSend={dictationAvailable ? (
          <DictationButton
            dictation={dictation}
            onStartRequest={requestDictation}
            languages={dictationInfo?.languages || []}
            language={dictationLanguage}
            onLanguage={chooseDictationLanguage}
          />
        ) : dictationInfo && !dictationInfo.available ? (
          <button type="button" className="fs-dict-btn" disabled
            aria-label={`Dictation unavailable: ${dictationInfo.reason || 'not configured'}`}
            title={`Dictation unavailable: ${dictationInfo.reason || 'not configured'}`}>
            <MicOff size={17} aria-hidden="true" />
          </button>
        ) : null}
        tools={(
          <ComposerTools
            catalog={modelCatalog}
            disabled={isStreaming}
          />
        )}
        status={statusActive ? (
          <ComposerStatus
            dictation={dictation}
            maxSeconds={dictationInfo?.max_seconds || 60}
            disclosure={dictationInfo?.disclosure}
            pendingConsent={pendingConsent}
            onConsent={acceptDictation}
            onDecline={() => setPendingConsent(false)}
            notice={modelCatalog.notice}
            onDismissNotice={modelCatalog.clearNotice}
          />
        ) : null}
      />
    </div>
  );
};

export default DarkChatInterface;
