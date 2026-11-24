import React from 'react';
import { ChevronDown, Mic, Square, X, Loader2 } from 'lucide-react';
import MenuButton from '../ui/MenuButton';

const EFFORT_HELP = {
  low: 'Quicker, lighter reasoning',
  medium: 'Balanced reasoning',
  high: 'Deeper reasoning; slower',
};

const formatClock = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

const LANGUAGE_HELP = {
  auto: 'Detect the spoken language automatically',
  en: 'Always transcribe as English',
  bn: 'Always transcribe as Bangla',
};

/**
 * Secondary composer row: model picker and reasoning effort (shown only when
 * the selected model genuinely supports a reasoning-effort control).
 */
export function ComposerTools({ catalog, disabled = false }) {
  const { models, status, selectedModel, effort, setModel, setEffort } = catalog;

  const modelItems = models.map((m) => ({
    label: m.label,
    description: m.available ? m.description : (m.unavailable_reason || 'Unavailable'),
    hint: !m.available ? 'Unavailable' : (m.preview ? 'Preview' : undefined),
    disabled: !m.available,
    checked: selectedModel?.id === m.id,
    onSelect: () => setModel(m.id),
  }));

  const effortItems = (selectedModel?.efforts || []).map((e) => ({
    label: e.label,
    description: EFFORT_HELP[e.id],
    checked: effort === e.id,
    onSelect: () => setEffort(e.id),
  }));
  const effortLabel = selectedModel?.efforts?.find((e) => e.id === effort)?.label;

  return (
    <div className="fs-composer-tools" role="group" aria-label="Response options">
      {status === 'error' ? (
        <span className="fs-tool-note">Model options unavailable · using server default</span>
      ) : selectedModel ? (
        <MenuButton
          label={`Model: ${selectedModel.label}. Change model`}
          items={modelItems}
          placement="top-start"
          buttonClassName="fs-tool"
          menuClassName="fs-menu--picker"
          disabled={disabled}
          buttonTitle={selectedModel.description}
        >
          <span>{selectedModel.label}</span>
          {selectedModel.preview && <span className="fs-tool-tag">Preview</span>}
          <ChevronDown size={12} className="fs-tool-chevron" aria-hidden="true" />
        </MenuButton>
      ) : (
        <span className="fs-tool-note" aria-live="polite">{status === 'loading' ? 'Loading models…' : 'No model available'}</span>
      )}

      {effortItems.length > 0 && (
        <MenuButton
          label={`Reasoning effort: ${effortLabel}. Change reasoning effort`}
          items={effortItems}
          placement="top-start"
          buttonClassName="fs-tool"
          menuClassName="fs-menu--picker"
          disabled={disabled}
          buttonTitle="How much the model reasons before answering"
        >
          <span className="fs-tool-sub">Reasoning</span>
          <span className="fs-tool-dot" aria-hidden="true">·</span>
          <span>{effortLabel}</span>
          <ChevronDown size={12} className="fs-tool-chevron" aria-hidden="true" />
        </MenuButton>
      )}

    </div>
  );
}

/**
 * Mic / stop / cancel controls shown next to Send. While idle, a small
 * attached chevron opens microphone settings (transcription language).
 */
export function DictationButton({ dictation, onStartRequest, languages = [], language = 'auto', onLanguage }) {
  const { state, elapsed, stop, cancel } = dictation;

  if (state === 'recording') {
    return (
      <>
        <button type="button" className="fs-dict-btn fs-dict-btn--ghost" onClick={cancel}
          aria-label="Cancel dictation" title="Cancel dictation (discard recording)">
          <X size={16} aria-hidden="true" />
        </button>
        <button type="button" className="fs-dict-btn fs-dict-btn--rec" onClick={stop}
          aria-label={`Stop dictation, ${elapsed} seconds recorded`} title="Stop and transcribe">
          <span className="fs-rec-dot" aria-hidden="true" />
          <span className="fs-rec-time" aria-hidden="true">{formatClock(elapsed)}</span>
          <Square size={12} fill="currentColor" aria-hidden="true" />
        </button>
      </>
    );
  }
  if (state === 'transcribing' || state === 'starting') {
    return (
      <button type="button" className="fs-dict-btn" disabled={state === 'starting'}
        onClick={state === 'transcribing' ? cancel : undefined}
        aria-label={state === 'transcribing' ? 'Transcribing. Cancel transcription' : 'Starting microphone'}
        title={state === 'transcribing' ? 'Transcribing… click to cancel' : 'Starting microphone…'}>
        <Loader2 size={17} className="fs-spin" aria-hidden="true" />
      </button>
    );
  }
  const current = languages.find((l) => l.id === language);
  const languageName = language === 'auto' ? 'automatic' : current?.label || language;
  return (
    <div className="fs-dict-group" role="group" aria-label="Voice dictation">
      <button type="button" className="fs-dict-btn fs-dict-btn--main" onClick={onStartRequest}
        aria-label={`Dictate a message (language: ${languageName})`} title="Dictate (speech to text)">
        <Mic size={17} aria-hidden="true" />
      </button>
      {languages.length > 0 && (
        <MenuButton
          label="Microphone settings"
          items={languages.map((l, index) => ({
            heading: index === 0 ? 'Dictation language' : undefined,
            label: l.id === 'auto' ? 'Detect automatically' : l.label,
            description: LANGUAGE_HELP[l.id],
            checked: language === l.id,
            onSelect: () => onLanguage?.(l.id),
          }))}
          placement="top-end"
          buttonClassName="fs-dict-btn fs-dict-btn--more"
          menuClassName="fs-menu--picker"
          buttonTitle={`Microphone settings · language: ${languageName}`}
        >
          <ChevronDown size={12} aria-hidden="true" />
        </MenuButton>
      )}
    </div>
  );
}

/** One-line status under the composer for dictation and model notices. */
export function ComposerStatus({ dictation, maxSeconds, disclosure, pendingConsent, onConsent, onDecline, notice, onDismissNotice }) {
  if (pendingConsent) {
    return (
      <div className="fs-composer-status fs-composer-status--consent" role="dialog" aria-label="Voice dictation">
        <span>{disclosure}</span>
        <span className="fs-status-actions">
          <button type="button" className="fs-link-btn fs-link-btn--strong" onClick={onConsent} autoFocus>Start dictation</button>
          <button type="button" className="fs-link-btn" onClick={onDecline}>Not now</button>
        </span>
      </div>
    );
  }
  if (dictation.error) {
    return (
      <div className="fs-composer-status fs-composer-status--error" role="alert">
        <span>{dictation.error}</span>
        <button type="button" className="fs-link-btn" onClick={dictation.clearError} aria-label="Dismiss dictation message">Dismiss</button>
      </div>
    );
  }
  if (dictation.state === 'recording') {
    return (
      <div className="fs-composer-status" role="status">
        Listening… stops automatically at {formatClock(maxSeconds)}. Your text will appear here to review before sending.
      </div>
    );
  }
  if (dictation.state === 'transcribing') {
    return <div className="fs-composer-status" role="status">Transcribing…</div>;
  }
  if (notice) {
    return (
      <div className="fs-composer-status" role="status">
        <span>{notice}</span>
        <button type="button" className="fs-link-btn" onClick={onDismissNotice}>Dismiss</button>
      </div>
    );
  }
  return null;
}
