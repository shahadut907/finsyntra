import React, { useState } from 'react';
import { FileText } from 'lucide-react';
import MessageContent from './MessageContent';
import SourceViewer from './SourceViewer';
import ErrorChip from '../ui/ErrorChip';
import { formatTime } from '../../lib/utils';
import finsolveLogo from '../../assets/finsyntra-logo.png';

// Existing brand mark from the repository, shown as the assistant avatar.
const AssistantAvatar = () => (
  <span className="fs-avatar fs-avatar--assistant" role="img" aria-label="FinSyntra assistant">
    <img src={finsolveLogo} alt="" />
  </span>
);

// Uploads are stored as <name>_<32-hex id>.<ext>; show the original name.
const displaySourceName = (source) => String(source).replace(/_[0-9a-f]{32}(?=\.[^.]+$)/, '');

const Dots = () => (
  <span className="fs-dots" aria-hidden="true">
    <i />
    <i />
    <i />
  </span>
);

/**
 * One transcript entry. The surface is a flat translucent block: no
 * backdrop-filter, no transform, and no hover rule that changes size or
 * position — hover may only soften the border color (see .fs-bubble in
 * glass.css). Memoized so streaming tokens re-render only the live message.
 */
export const ChatMessage = React.memo(function ChatMessage({ message, userInitial, onRetry }) {
  const isUser = message.sender === 'user';
  const uniqueSources = !isUser && message.sources?.length ? [...new Set(message.sources)] : [];
  const showBubble = isUser || Boolean(message.text?.trim()) || !message.error || uniqueSources.length > 0;
  const [openSource, setOpenSource] = useState(null);

  return (
    <article
      className={`fs-msg ${isUser ? 'fs-msg--user' : 'fs-msg--assistant'}`}
      aria-label={isUser ? 'You' : 'FinSyntra assistant'}
    >
      {isUser ? (
        <div className="fs-avatar fs-avatar--user" aria-hidden="true">{userInitial}</div>
      ) : (
        <AssistantAvatar />
      )}

      <div className="fs-msg-body">
        {/* A failed turn with no text shows only its error chip, not an empty pane. */}
        {showBubble && (
        <div className={`fs-bubble${message.isError ? ' fs-bubble--error' : ''}`}>
          {isUser ? message.text : <MessageContent text={message.text} />}

          {uniqueSources.length > 0 && (
            <div className="fs-sources">
              <p className="fs-sources-label">Sources</p>
              <ul className="fs-sources-list">
                {uniqueSources.map((source) => (
                  <li key={source}>
                    <button
                      type="button"
                      className="fs-chip fs-chip--button"
                      title={`Open ${displaySourceName(source)}`}
                      onClick={() => setOpenSource(source)}
                    >
                      <FileText size={12} aria-hidden="true" />
                      <span>{displaySourceName(source)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        )}

        <div className="fs-meta">
          <span>{formatTime(message.timestamp)}</span>
          {message.confidence ? <span>{Math.round(message.confidence * 100)}% confident</span> : null}
          {!isUser && message.model && (
            <span className="fs-meta-model" title="Model and reasoning effort that produced this answer">
              {message.model.label}
              {message.model.reasoning_effort
                ? ` · ${message.model.reasoning_effort.charAt(0).toUpperCase()}${message.model.reasoning_effort.slice(1)} reasoning`
                : ''}
            </span>
          )}
          {message.isStreaming && (
            <span className="fs-meta-live">
              <Dots />
              <span>{message.statusText || 'Responding…'}</span>
            </span>
          )}
        </div>

        {message.error && (
          <ErrorChip error={message.error} onRetry={onRetry} messageId={message.id} />
        )}

        {openSource && (
          <SourceViewer
            source={openSource}
            displayName={displaySourceName(openSource)}
            onClose={() => setOpenSource(null)}
          />
        )}
      </div>
    </article>
  );
});

export const ThinkingMessage = ({ statusText }) => (
  <article className="fs-msg fs-msg--assistant" aria-label="FinSyntra assistant">
    <AssistantAvatar />
    <div className="fs-msg-body">
      <div className="fs-bubble">
        <span className="fs-meta-live" style={{ fontSize: '0.875rem' }}>
          <Dots />
          <span>{statusText || 'Thinking…'}</span>
        </span>
      </div>
    </div>
  </article>
);

export default ChatMessage;
