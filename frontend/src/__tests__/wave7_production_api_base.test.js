/**
 * Wave 7 closure: a production build must never silently target the
 * visitor's localhost. Every module that resolves an API base URL must
 * default to same-origin when NODE_ENV isn't 'development' and no
 * REACT_APP_API_URL / REACT_APP_API_BASE_URL / NEXT_PUBLIC_/VITE_ variant is
 * supplied at build time.
 */

const ORIGINAL_ENV = { ...process.env };

function freshRequire(modulePath) {
  jest.resetModules();
  return require(modulePath);
}

describe('Wave 7 production API base safety', () => {
  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
    jest.resetModules();
  });

  test('config/env.js API_BASE_URL is same-origin in production, not localhost', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.REACT_APP_API_URL;
    delete process.env.REACT_APP_API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    delete process.env.VITE_API_BASE_URL;

    const { API_BASE_URL } = freshRequire('../config/env');
    expect(API_BASE_URL).not.toContain('localhost:8000');
    expect(API_BASE_URL).toBe(window.location.origin);
  });

  test('lib/apiClient.js API_BASE is same-origin in production, not localhost', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.REACT_APP_API_URL;
    delete process.env.REACT_APP_API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    delete process.env.VITE_API_BASE_URL;

    const { API_BASE } = freshRequire('../lib/apiClient');
    expect(API_BASE).not.toContain('localhost:8000');
    expect(API_BASE).toBe(window.location.origin);
  });

  test('config/chat.js CHAT_BASE is same-origin in production, not localhost', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.REACT_APP_API_URL;
    delete process.env.REACT_APP_API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    delete process.env.VITE_API_BASE_URL;

    const { CHAT_BASE, CHAT_STREAM_URL } = freshRequire('../config/chat');
    expect(CHAT_BASE).not.toContain('localhost:8000');
    expect(CHAT_BASE).toBe(window.location.origin);
    // SSE URL composes cleanly off same-origin, no double /api or broken path.
    expect(CHAT_STREAM_URL).toBe(`${window.location.origin}/api/chat/stream`);
  });

  test('an explicit REACT_APP_API_URL still wins in any environment', () => {
    process.env.NODE_ENV = 'production';
    process.env.REACT_APP_API_URL = 'https://finsolve.example.com';

    const { API_BASE_URL } = freshRequire('../config/env');
    const { API_BASE } = freshRequire('../lib/apiClient');

    expect(API_BASE_URL).toBe('https://finsolve.example.com');
    expect(API_BASE).toBe('https://finsolve.example.com');
  });

  test('development keeps the explicit local backend default', () => {
    process.env.NODE_ENV = 'development';
    delete process.env.REACT_APP_API_URL;

    const { API_BASE_URL } = freshRequire('../config/env');
    expect(API_BASE_URL).toBe('http://localhost:8000');
  });
});
