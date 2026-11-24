import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch } from '../lib/apiClient';

// Ordered by preference; all are accepted by the transcription endpoint.
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];

const pickMimeType = () => {
  if (typeof window === 'undefined' || typeof window.MediaRecorder === 'undefined') return null;
  if (typeof window.MediaRecorder.isTypeSupported !== 'function') return '';
  return MIME_CANDIDATES.find((type) => window.MediaRecorder.isTypeSupported(type)) ?? '';
};

export const dictationSupported = () => (
  typeof navigator !== 'undefined'
  && !!navigator.mediaDevices?.getUserMedia
  && typeof window !== 'undefined'
  && typeof window.MediaRecorder !== 'undefined'
);

const ERROR_MESSAGES = {
  NotAllowedError: 'Microphone access was blocked. Allow it in your browser’s site settings to dictate.',
  SecurityError: 'Microphone access was blocked. Allow it in your browser’s site settings to dictate.',
  NotFoundError: 'No microphone was found.',
  NotReadableError: 'The microphone is in use by another application.',
  AbortError: 'The microphone could not be started.',
};

/**
 * Speech -> text for the composer. Records only after an explicit start()
 * (a user click), uploads the clip for transcription, and hands the text to
 * ``onTranscript``; it never sends a chat message.
 *
 * state: idle | starting | recording | transcribing
 * The microphone is released on stop, cancel, error and unmount.
 */
export default function useDictation({ onTranscript, maxSeconds = 60, language = 'auto' }) {
  const [state, setState] = useState('idle');
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);

  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const startedAtRef = useRef(0);
  const discardRef = useRef(false);
  const uploadAbortRef = useRef(null);
  const mountedRef = useRef(true);
  const languageRef = useRef(language);
  const onTranscriptRef = useRef(onTranscript);

  useEffect(() => { languageRef.current = language; }, [language]);
  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);

  const releaseMic = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const safeSet = (fn) => { if (mountedRef.current) fn(); };

  const upload = useCallback(async (blob, mimeType) => {
    if (!blob || blob.size < 1024) {
      safeSet(() => { setError('No audio was captured. Please try again.'); setState('idle'); });
      return;
    }
    safeSet(() => setState('transcribing'));
    const controller = new AbortController();
    uploadAbortRef.current = controller;
    const ext = mimeType.includes('mp4') ? 'mp4' : mimeType.includes('ogg') ? 'ogg' : 'webm';
    const form = new FormData();
    form.append('audio', new File([blob], `dictation.${ext}`, { type: mimeType || 'audio/webm' }));
    form.append('language', languageRef.current || 'auto');
    try {
      const response = await apiFetch('/api/speech/transcribe', { method: 'POST', body: form, signal: controller.signal });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const fallback = response.status === 429 ? 'Too many dictations. Please wait a minute.' : 'Transcription failed. Please try again.';
        safeSet(() => setError(data?.message || fallback));
        return;
      }
      const text = (data?.text || '').trim();
      if (!text) {
        safeSet(() => setError('No speech was detected. Please try again.'));
        return;
      }
      if (mountedRef.current) onTranscriptRef.current?.(text);
    } catch (err) {
      if (err?.name !== 'AbortError') {
        safeSet(() => setError('Transcription failed. Check your connection and try again.'));
      }
    } finally {
      uploadAbortRef.current = null;
      safeSet(() => setState('idle'));
    }
  }, []);

  const start = useCallback(async () => {
    if (state !== 'idle') return;
    setError(null);
    if (!dictationSupported()) {
      setError('Voice dictation is not supported in this browser.');
      return;
    }
    setState('starting');
    let stream;
    try {
      // Permission is requested here, i.e. only after the user clicked.
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      safeSet(() => {
        setError(ERROR_MESSAGES[err?.name] || 'The microphone could not be started.');
        setState('idle');
      });
      return;
    }
    if (!mountedRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    streamRef.current = stream;
    const mimeType = pickMimeType() || '';
    let recorder;
    try {
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    } catch {
      releaseMic();
      setError('Voice dictation is not supported in this browser.');
      setState('idle');
      return;
    }
    recorderRef.current = recorder;
    chunksRef.current = [];
    discardRef.current = false;
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      releaseMic();
      recorderRef.current = null;
      const chunks = chunksRef.current;
      chunksRef.current = [];
      if (discardRef.current) {
        safeSet(() => setState('idle'));
        return;
      }
      const type = recorder.mimeType || mimeType || 'audio/webm';
      upload(new Blob(chunks, { type }), type);
    };
    recorder.start(250);
    startedAtRef.current = Date.now();
    setElapsed(0);
    setState('recording');
    timerRef.current = setInterval(() => {
      const seconds = Math.floor((Date.now() - startedAtRef.current) / 1000);
      safeSet(() => setElapsed(seconds));
      if (seconds >= maxSeconds && recorderRef.current?.state === 'recording') {
        recorderRef.current.stop(); // hard cap; the clip is still transcribed
      }
    }, 250);
  }, [state, maxSeconds, releaseMic, upload]);

  const stop = useCallback(() => {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
  }, []);

  const cancel = useCallback(() => {
    discardRef.current = true;
    if (recorderRef.current?.state === 'recording') {
      recorderRef.current.stop();
    } else {
      releaseMic();
    }
    uploadAbortRef.current?.abort();
    setState('idle');
  }, [releaseMic]);

  // Release the microphone and abandon any upload when the composer unmounts
  // (navigation, conversation change that remounts, sign-out).
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      discardRef.current = true;
      try {
        if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
      } catch {
        /* recorder already inactive */
      }
      uploadAbortRef.current?.abort();
      if (timerRef.current) clearInterval(timerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  return { state, error, elapsed, start, stop, cancel, clearError: () => setError(null) };
}
