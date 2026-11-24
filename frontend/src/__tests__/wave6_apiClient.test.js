import { apiFetch, getCsrfToken } from '../lib/apiClient';

const response = (status) => ({ status, ok: status >= 200 && status < 300 });

describe('Wave 6 shared API security behavior', () => {
  beforeEach(() => {
    document.cookie = 'csrf_token=wave6%20token; path=/';
    global.fetch = jest.fn();
  });

  afterEach(() => jest.restoreAllMocks());

  test('unsafe cookie request carries the readable CSRF cookie', async () => {
    fetch.mockResolvedValue(response(200));
    await apiFetch('/api/chat', { method: 'POST', body: JSON.stringify({ message: 'hi' }) });
    const [, init] = fetch.mock.calls[0];
    expect(getCsrfToken()).toBe('wave6 token');
    expect(init.credentials).toBe('include');
    expect(init.headers.get('X-CSRF-Token')).toBe('wave6 token');
  });

  test('FormData keeps browser content boundary and carries CSRF', async () => {
    fetch.mockResolvedValue(response(200));
    await apiFetch('/api/admin/upload-department-data', {
      method: 'POST', body: new FormData()
    });
    const [, init] = fetch.mock.calls[0];
    expect(init.headers.has('Content-Type')).toBe(false);
    expect(init.headers.get('X-CSRF-Token')).toBe('wave6 token');
  });

  test('401 performs one CSRF-protected refresh and retries once', async () => {
    fetch
      .mockResolvedValueOnce(response(401))
      .mockResolvedValueOnce(response(200))
      .mockResolvedValueOnce(response(200));
    const result = await apiFetch('/api/documents/list');
    expect(result.status).toBe(200);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls[1][0]).toContain('/auth/refresh');
    expect(fetch.mock.calls[1][1].headers['X-CSRF-Token']).toBe('wave6 token');
  });
});
