import React from 'react';
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react';
import MenuButton from '../components/ui/MenuButton';
import { ComposerTools, DictationButton } from '../components/chat/ComposerControls';
import useDictation from '../hooks/useDictation';

jest.mock('../lib/apiClient', () => ({
  apiFetch: jest.fn(),
  ensureAuthenticatedSession: jest.fn(),
}));
const apiClient = require('../lib/apiClient');
const { chatService } = require('../services/chatService');

const CATALOG = {
  default_model: 'prism',
  models: [
    { id: 'prism', label: 'Prism', description: 'Fast', available: true, preview: false,
      efforts: [{ id: 'low', label: 'Low' }, { id: 'medium', label: 'Medium' }, { id: 'high', label: 'High' }], default_effort: 'low' },
    { id: 'atlas', label: 'Atlas', description: 'Balanced', available: false, unavailable_reason: 'Not available', preview: false,
      efforts: [], default_effort: null },
  ],
};

const catalogState = (overrides = {}) => ({
  models: CATALOG.models, status: 'ready', selectedModel: CATALOG.models[0], effort: 'low',
  setModel: jest.fn(), setEffort: jest.fn(), ...overrides,
});

describe('chat request carries the allowlisted selection', () => {
  let created;
  beforeEach(() => {
    created = [];
    apiClient.ensureAuthenticatedSession.mockResolvedValue(true);
    global.EventSource = class {
      static CLOSED = 2;
      constructor(url) { this.url = url; this.readyState = 0; created.push(this); }
      close() { this.readyState = 2; }
    };
  });

  test('model and effort become query parameters', async () => {
    const pending = chatService.sendMessage({ message: 'Leave policy?', sessionId: 's1', model: 'atlas', effort: 'high' });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const url = new URL(created[0].url);
    expect(url.searchParams.get('model')).toBe('atlas');
    expect(url.searchParams.get('effort')).toBe('high');
    created[0].onmessage({ data: '[DONE]' });
    await pending;
  });

  test('no selection sends no model parameter (server default applies)', async () => {
    const pending = chatService.sendMessage({ message: 'Leave policy?', sessionId: 's1' });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(new URL(created[0].url).searchParams.has('model')).toBe(false);
    created[0].onmessage({ data: '[DONE]' });
    await pending;
  });
});

describe('refused stream diagnosis never resends the message', () => {
  test('withdrawn model is reported as unavailable', async () => {
    apiClient.apiFetch.mockResolvedValue({ ok: true, status: 200, json: async () => CATALOG });
    const err = await chatService.diagnoseStreamRefusal('atlas', null);
    expect(err.code).toBe('MODEL_UNAVAILABLE');
    expect(err.message).toMatch(/Atlas is unavailable/);
    expect(apiClient.apiFetch).toHaveBeenCalledWith('/api/chat/models');
  });

  test('signed-out session keeps the authentication message', async () => {
    apiClient.apiFetch.mockResolvedValue({ ok: false, status: 401 });
    expect(await chatService.diagnoseStreamRefusal('prism', 'low')).toBeNull();
  });

  test('available model means a connection problem, not auth', async () => {
    apiClient.apiFetch.mockResolvedValue({ ok: true, status: 200, json: async () => CATALOG });
    const err = await chatService.diagnoseStreamRefusal('prism', 'low');
    expect(err.message).toMatch(/Connection to server failed/);
  });
});

describe('composer pickers', () => {
  test('shows model and effort; unavailable model is disabled', () => {
    render(<ComposerTools catalog={catalogState()} />);
    expect(screen.getByRole('button', { name: /^Model: Prism/ })).toBeTruthy();
    const reasoning = screen.getByRole('button', { name: /^Reasoning effort: Low/ });
    expect(reasoning.textContent).toBe('Reasoning·Low');
    // model trigger: name + chevron only (no decorative icon before the name)
    const modelBtn = screen.getByRole('button', { name: /^Model: Prism/ });
    expect(modelBtn.textContent).toBe('Prism');
    expect(modelBtn.querySelectorAll('svg')).toHaveLength(1);
    expect(modelBtn.lastElementChild.tagName.toLowerCase()).toBe('svg');
    // the dictation-language selector no longer lives in the composer row
    expect(screen.queryByRole('button', { name: /language/i })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /^Model: Prism/ }));
    const atlas = screen.getByRole('menuitemradio', { name: /Atlas/ });
    expect(atlas.getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByRole('menuitemradio', { name: /Prism/ }).getAttribute('aria-checked')).toBe('true');
  });

  test('effort control is hidden when the model has no reasoning control', () => {
    const noEffort = { ...CATALOG.models[0], efforts: [] };
    render(<ComposerTools catalog={catalogState({ selectedModel: noEffort, effort: null })} />);
    expect(screen.queryByRole('button', { name: /Reasoning effort/ })).toBeNull();
  });

  test('reasoning label follows the selected effort', () => {
    const { rerender } = render(<ComposerTools catalog={catalogState({ effort: 'medium' })} />);
    expect(screen.getByRole('button', { name: /^Reasoning effort/ }).textContent).toBe('Reasoning·Medium');
    rerender(<ComposerTools catalog={catalogState({ effort: 'high' })} />);
    expect(screen.getByRole('button', { name: /^Reasoning effort/ }).textContent).toBe('Reasoning·High');
    fireEvent.click(screen.getByRole('button', { name: /^Reasoning effort/ }));
    expect(screen.getByRole('menuitemradio', { name: /High/ }).getAttribute('aria-checked')).toBe('true');
  });

  test('dictation language lives in the microphone settings menu', () => {
    const onLanguage = jest.fn();
    render(
      <DictationButton
        dictation={{ state: 'idle' }}
        onStartRequest={() => {}}
        languages={[{ id: 'auto', label: 'Auto' }, { id: 'en', label: 'English' }, { id: 'bn', label: 'বাংলা' }]}
        language="auto"
        onLanguage={onLanguage}
      />
    );
    expect(screen.getByRole('button', { name: /Dictate a message \(language: automatic\)/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Microphone settings' }));
    expect(screen.getByRole('menuitemradio', { name: /Detect automatically/ }).getAttribute('aria-checked')).toBe('true');
    fireEvent.click(screen.getByRole('menuitemradio', { name: /বাংলা/ }));
    expect(onLanguage).toHaveBeenCalledWith('bn');
  });

  test('catalog failure is stated, not faked', () => {
    render(<ComposerTools catalog={catalogState({ status: 'error', selectedModel: null })} />);
    expect(screen.getByText(/Model options unavailable/)).toBeTruthy();
  });

  test('MenuButton keeps plain menuitems for existing menus', () => {
    render(<MenuButton label="Actions" items={[{ label: 'Export', onSelect: () => {} }]}>x</MenuButton>);
    fireEvent.click(screen.getByRole('button', { name: 'Actions' }));
    expect(screen.getByRole('menuitem', { name: 'Export' })).toBeTruthy();
  });
});

describe('useDictation', () => {
  let track;
  let recorders;
  beforeEach(() => {
    track = { stop: jest.fn(), readyState: 'live' };
    recorders = [];
    Object.defineProperty(global.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: jest.fn().mockResolvedValue({ getTracks: () => [track] }) },
    });
    global.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor(stream, opts) { this.stream = stream; this.mimeType = opts?.mimeType || 'audio/webm'; this.state = 'inactive'; recorders.push(this); }
      start() { this.state = 'recording'; }
      stop() { this.state = 'inactive'; this.ondataavailable?.({ data: new Blob(['x'.repeat(4096)]) }); this.onstop?.(); }
    };
  });

  test('microphone is requested only on start, released on cancel, nothing transcribed', async () => {
    const onTranscript = jest.fn();
    const { result } = renderHook(() => useDictation({ onTranscript }));
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    await act(async () => { await result.current.start(); });
    expect(result.current.state).toBe('recording');
    act(() => result.current.cancel());
    expect(track.stop).toHaveBeenCalled();
    expect(onTranscript).not.toHaveBeenCalled();
    expect(apiClient.apiFetch).not.toHaveBeenCalled();
    expect(result.current.state).toBe('idle');
  });

  test('stop uploads and hands back text (never sends a chat message)', async () => {
    apiClient.apiFetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ text: 'ছুটির নীতি' }) });
    const onTranscript = jest.fn();
    const { result } = renderHook(() => useDictation({ onTranscript, language: 'bn' }));
    await act(async () => { await result.current.start(); });
    await act(async () => { result.current.stop(); await new Promise((r) => setTimeout(r, 0)); });
    expect(track.stop).toHaveBeenCalled();
    const [path, init] = apiClient.apiFetch.mock.calls[0];
    expect(path).toBe('/api/speech/transcribe');
    expect(init.body.get('language')).toBe('bn');
    expect(onTranscript).toHaveBeenCalledWith('ছুটির নীতি');
  });

  test('unmount while recording releases the microphone', async () => {
    const { result, unmount } = renderHook(() => useDictation({ onTranscript: jest.fn() }));
    await act(async () => { await result.current.start(); });
    unmount();
    expect(track.stop).toHaveBeenCalled();
    expect(apiClient.apiFetch).not.toHaveBeenCalled();
  });

  test('permission denial is explained', async () => {
    navigator.mediaDevices.getUserMedia.mockRejectedValue(Object.assign(new Error('no'), { name: 'NotAllowedError' }));
    const { result } = renderHook(() => useDictation({ onTranscript: jest.fn() }));
    await act(async () => { await result.current.start(); });
    expect(result.current.error).toMatch(/blocked/);
    expect(result.current.state).toBe('idle');
  });

  test('unsupported browser is explained', async () => {
    delete global.MediaRecorder;
    const { result } = renderHook(() => useDictation({ onTranscript: jest.fn() }));
    await act(async () => { await result.current.start(); });
    expect(result.current.error).toMatch(/not supported/);
  });

  test('provider failure surfaces the server message', async () => {
    apiClient.apiFetch.mockResolvedValue({ ok: false, status: 503, json: async () => ({ message: 'The transcription service is busy.' }) });
    const onTranscript = jest.fn();
    const { result } = renderHook(() => useDictation({ onTranscript }));
    await act(async () => { await result.current.start(); });
    await act(async () => { result.current.stop(); await new Promise((r) => setTimeout(r, 0)); });
    expect(result.current.error).toMatch(/busy/);
    expect(onTranscript).not.toHaveBeenCalled();
  });
});
