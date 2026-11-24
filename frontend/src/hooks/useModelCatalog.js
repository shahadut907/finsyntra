import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiFetch } from '../lib/apiClient';

const STORAGE_KEY = 'finsolve.chatModel';

const readStored = () => {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
};

const writeStored = (value) => {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* preference just isn't remembered */
  }
};

/**
 * Loads the server's model catalog (/api/chat/models) and keeps the user's
 * model + thinking-effort choice. The choice only ever contains ids the
 * server listed as available; the server re-validates every request.
 *
 * Returns { catalog, status, model, effort, selectedModel, setModel,
 *           setEffort, sendParams, dictation, refresh }.
 */
export default function useModelCatalog() {
  const [catalog, setCatalog] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | ready | error
  const [choice, setChoice] = useState(readStored);
  const [notice, setNotice] = useState(null);

  const refresh = useCallback(async () => {
    setStatus((s) => (s === 'ready' ? s : 'loading'));
    try {
      const response = await apiFetch('/api/chat/models');
      if (!response.ok) throw new Error(`catalog ${response.status}`);
      const data = await response.json();
      setCatalog(data);
      setStatus('ready');
    } catch {
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const models = useMemo(() => catalog?.models || [], [catalog]);

  // Resolve the stored choice against what the server offers right now.
  const selectedModel = useMemo(() => {
    if (!models.length) return null;
    const wanted = models.find((m) => m.id === choice?.model && m.available);
    return wanted || models.find((m) => m.id === catalog?.default_model && m.available)
      || models.find((m) => m.available) || null;
  }, [models, choice, catalog]);

  const effort = useMemo(() => {
    if (!selectedModel || !selectedModel.efforts?.length) return null;
    const ids = selectedModel.efforts.map((e) => e.id);
    if (choice?.model === selectedModel.id && ids.includes(choice?.effort)) return choice.effort;
    return selectedModel.default_effort || ids[0];
  }, [selectedModel, choice]);

  // A remembered model that is no longer offered is replaced by the default
  // in the picker, and the user is told so (never a silent swap).
  useEffect(() => {
    if (!choice?.model || !models.length || !selectedModel) return;
    if (selectedModel.id !== choice.model) {
      const old = models.find((m) => m.id === choice.model);
      setNotice(`${old?.label || 'Your saved model'} is unavailable; ${selectedModel.label} is selected.`);
    }
  }, [choice, models, selectedModel]);

  const setModel = useCallback((modelId) => {
    const target = models.find((m) => m.id === modelId);
    if (!target || !target.available) return;
    const next = { model: target.id, effort: target.default_effort || null };
    setChoice(next);
    writeStored(next);
    setNotice(null);
  }, [models]);

  const setEffort = useCallback((effortId) => {
    if (!selectedModel?.efforts?.some((e) => e.id === effortId)) return;
    const next = { model: selectedModel.id, effort: effortId };
    setChoice(next);
    writeStored(next);
  }, [selectedModel]);

  // What chat requests carry. Before the catalog loads (or if it failed),
  // nothing is sent and the server applies its default.
  const sendParams = useMemo(
    () => (selectedModel ? { model: selectedModel.id, effort } : {}),
    [selectedModel, effort]
  );

  return {
    catalog,
    models,
    status,
    selectedModel,
    effort,
    setModel,
    setEffort,
    sendParams,
    dictation: catalog?.dictation || null,
    notice,
    clearNotice: () => setNotice(null),
    refresh,
  };
}
