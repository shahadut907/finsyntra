import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { FileText, X } from 'lucide-react';
import { apiFetch } from '../../lib/apiClient';
import useModalDialogs from '../../hooks/useModalDialogs';

/**
 * Shows the indexed passages of one cited source. The server applies the
 * same tenant + department filter as chat retrieval and answers 404 for
 * anything the signed-in user could not retrieve, so this never reveals
 * more than the answer that cited it.
 */
export default function SourceViewer({ source, displayName, onClose }) {
  const [state, setState] = useState({ status: 'loading', data: null });

  useModalDialogs({ active: true, onEscape: onClose, selector: '.fs-dialog-root' });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await apiFetch(`/api/documents/source/${encodeURIComponent(source)}`);
        if (cancelled) return;
        if (!response.ok) {
          setState({ status: response.status === 404 ? 'unavailable' : 'error', data: null });
          return;
        }
        setState({ status: 'ready', data: await response.json() });
      } catch {
        if (!cancelled) setState({ status: 'error', data: null });
      }
    })();
    return () => { cancelled = true; };
  }, [source]);

  const passages = state.data?.passages || [];

  return createPortal(
    <div
      className="fs-dialog-root"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="fs-dialog fs-dialog--source">
        <div className="fs-source-head">
          <FileText size={16} aria-hidden="true" />
          <h2 className="fs-source-title" title={displayName}>{displayName}</h2>
          <button type="button" className="fs-btn fs-btn--icon fs-btn--ghost" onClick={onClose} aria-label="Close source">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        {state.data?.department && (
          <p className="fs-source-meta">Department: {state.data.department}</p>
        )}
        <div className="fs-source-body" aria-live="polite">
          {state.status === 'loading' && <p className="fs-source-meta">Loading source…</p>}
          {state.status === 'unavailable' && (
            <p className="fs-source-meta">This source is no longer available, or your account cannot open it.</p>
          )}
          {state.status === 'error' && (
            <p className="fs-source-meta">The source could not be loaded. Try again.</p>
          )}
          {state.status === 'ready' && passages.map((text, index) => (
            // Passages are fixed, ordered server text; index is a stable key.
            // eslint-disable-next-line react/no-array-index-key
            <p key={index} className="fs-source-passage">{text}</p>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
