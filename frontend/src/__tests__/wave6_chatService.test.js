jest.mock('../lib/apiClient', () => ({
  apiFetch: jest.fn(),
  ensureAuthenticatedSession: jest.fn(() => Promise.resolve(true)),
}));

import { ChatService } from '../services/chatService';
import { ensureAuthenticatedSession } from '../lib/apiClient';
import { waitFor } from '@testing-library/react';

class FakeEventSource {
  static CLOSED = 2;
  constructor(url, options) {
    this.url = url;
    this.options = options;
    this.readyState = 1;
    FakeEventSource.instances.push(this);
  }
  close() { this.readyState = FakeEventSource.CLOSED; this.closed = true; }
}
FakeEventSource.instances = [];

describe('Wave 6 EventSource lifecycle', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    global.EventSource = FakeEventSource;
    ensureAuthenticatedSession.mockResolvedValue(true);
  });

  test('auth preflight occurs before open and completion is delivered once', async () => {
    const service = new ChatService();
    const onComplete = jest.fn();
    const pending = service.sendMessageEventSource({
      message: 'hello', sessionId: 'owned-session', onComplete
    });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(ensureAuthenticatedSession).toHaveBeenCalledTimes(1);
    const stream = FakeEventSource.instances[0];
    expect(stream.options.withCredentials).toBe(true);
    expect(stream.url).not.toMatch(/token=/i);
    stream.onmessage({ data: JSON.stringify({ type: 'token', token: 'ok' }) });
    stream.onmessage({ data: JSON.stringify({ type: 'complete', success: true, generation_status: 'ok' }) });
    stream.onmessage({ data: '[DONE]' });
    stream.onmessage({ data: '[DONE]' });
    await expect(pending).resolves.toMatchObject({ response: 'ok' });
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(stream.closed).toBe(true);
  });

  test('abort closes the only stream and rejects without reconnecting', async () => {
    const service = new ChatService();
    const controller = new AbortController();
    const pending = service.sendMessageEventSource({
      message: 'hello', sessionId: 'owned-session', signal: controller.signal
    });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const stream = FakeEventSource.instances[0];
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(stream.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  test('a newer submit invalidates an older stream still in auth preflight', async () => {
    const service = new ChatService();
    let releaseFirst;
    ensureAuthenticatedSession
      .mockReturnValueOnce(new Promise(resolve => { releaseFirst = resolve; }))
      .mockResolvedValueOnce(true);
    const first = service.sendMessage({ message: 'first', sessionId: 'owned-session' });
    const second = service.sendMessage({ message: 'second', sessionId: 'owned-session' });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    releaseFirst(true);
    await expect(first).resolves.toMatchObject({ aborted: true });
    expect(FakeEventSource.instances).toHaveLength(1);
    service.abortCurrentStream();
    await expect(second).resolves.toMatchObject({ aborted: true });
  });
});
