// Unified API client with credentials + auth headers for all requests
//
// SECURITY: Authentication is exclusively via httpOnly cookies.
// No tokens are read from or written to localStorage.
// The backend sets session_token and refresh_token as httpOnly cookies.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.VITE_API_BASE_URL ||
  process.env.REACT_APP_API_BASE_URL ||
  process.env.REACT_APP_API_URL ||
  (process.env.NODE_ENV === 'development' ? 'http://localhost:8000' : window.location.origin);

// Helper to get cookie value (non-httpOnly cookies only, e.g. CSRF)
export const getCookie = (n) => {
  if (typeof document === 'undefined') return null;
  const cookie = document.cookie.split('; ').find(c => c.startsWith(n + '='));
  return cookie ? decodeURIComponent(cookie.substring(n.length + 1)) : null;
};

export const getCsrfToken = () => getCookie('csrf_token');

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

// Single-flight refresh state
let isRefreshing = false;
let refreshPromise = null;

// Callback for auth errors (set by AuthContext)
let authErrorCallback = null;
export const setAuthErrorCallback = (callback) => {
  authErrorCallback = callback;
};

// Debug logging helper
const authDebug = (data) => {
  if (typeof window !== 'undefined' && window.location.search.includes('debug=auth')) {
    console.debug('[FinSyntra auth]', data);
  }
};

export async function apiFetch(input, init = {}) {
  const headers = new Headers(init.headers || {});
  const method = (init.method || 'GET').toUpperCase();
  
  // Set Accept header if not already set
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  
  // Set Content-Type for requests with body, but only if not already set
  // This prevents overriding SSE-specific Content-Type settings
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  // SECURITY: Auth is handled exclusively via httpOnly cookies (credentials: 'include').
  // No Bearer token is attached from localStorage.
  
  // CSRF (cookie-based backends)
  const csrf = getCsrfToken();
  if (UNSAFE_METHODS.has(method) && csrf) headers.set('X-CSRF-Token', csrf);

  // Debug logging
  authDebug({
    url: input.startsWith('http') ? input : `${API_BASE}${input}`,
    method,
    authMethod: 'cookies only (httpOnly)',
    withCreds: true,
    csrf: !!csrf,
    accept: headers.get('Accept'),
    contentType: headers.get('Content-Type') || 'none'
  });

  const url = input.startsWith('http') ? input : `${API_BASE}${input}`;
  const res = await fetch(url, {
    credentials: 'include',  // <- important for cookie auth
    mode: 'cors',
    ...init,
    headers,
  });

  // Handle 401 with single-flight refresh
  if (res.status === 401 && !init._retried && !init._skipAuthRefresh) {
    authDebug({
      message: '401 received, attempting refresh',
      url: url,
      hasRefreshCookie: !!(getCookie('refresh_token') || getCookie('session_token'))
    });
    
    // If we're not on /auth/me or /auth/login, try to handle unauthorized
    const isAuthEndpoint = url.includes('/auth/login') || url.includes('/auth/demo-login') || url.includes('/auth/refresh');
    if (!isAuthEndpoint) {
      return handleUnauthorized(input, init);
    }
  }

  return res;
}

// Handle 401 responses with single-flight token refresh
async function handleUnauthorized(input, init) {
  // Check if we have refresh capability (refresh_token is httpOnly, so we
  // can't read it directly — we just attempt the refresh and let the backend
  // decide based on the cookie).
  
  // Single-flight refresh
  if (!isRefreshing) {
    isRefreshing = true;
    refreshPromise = performTokenRefresh();
  }

  const refreshSuccess = await refreshPromise;
  isRefreshing = false;
  refreshPromise = null;

  if (!refreshSuccess) {
    // Refresh failed, trigger auth error callback
    authDebug({ message: 'Refresh failed, triggering auth error callback' });
    
    // Legacy cleanup — remove any leftover keys from prior versions
    if (typeof window !== 'undefined') {
      window.__FINSOLVE_SESSION__ = null;
      localStorage.removeItem('finsolve_auth_token');
      localStorage.removeItem('accessToken');
      localStorage.removeItem('access_token');
    }
    
    if (authErrorCallback) {
      authErrorCallback();
    }
    
    return new Response(JSON.stringify({ error: 'Unauthorized — please sign in' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  // Retry the original request exactly once
  const retryInit = { ...init, _retried: true };
  return apiFetch(input, retryInit);
}

// Perform the actual token refresh
async function performTokenRefresh() {
  try {
    authDebug({ message: 'Attempting token refresh...' });
    
    const csrf = getCsrfToken();
    const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      mode: 'cors',
      headers: {
        'Content-Type': 'application/json',
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      }
    });

    if (!refreshRes.ok) {
      authDebug({ message: 'Token refresh failed with status', status: refreshRes.status });
      return false;
    }

    // The backend sets the new access token as an httpOnly cookie.
    // No need to store anything in localStorage.
    authDebug({ message: 'Token refresh successful (new cookie set by backend)' });
    return true;
  } catch (error) {
    console.error('Token refresh failed:', error);
    authDebug({ message: 'Token refresh error', error: error.message });
    return false;
  }
}

export async function refreshSession() {
  const refreshed = await performTokenRefresh();
  if (!refreshed && authErrorCallback) authErrorCallback();
  return refreshed;
}

// EventSource cannot expose a 401 response or add Authorization headers. A
// normal cookie-authenticated request first refreshes an expired access cookie,
// then the stream opens with credentials and no token in its URL.
export async function ensureAuthenticatedSession() {
  const response = await apiFetch('/auth/me', { method: 'GET' });
  return response.ok;
}

// Export conversation helper (JSON/Markdown/PDF)
export async function exportConversation(conversationId, format = 'json') {
  if (!conversationId) {
    throw new Error('Missing conversation id');
  }
  const encodedId = encodeURIComponent(conversationId);
  const encodedFormat = encodeURIComponent(format);
  const acceptHeader = format === 'pdf' ? 'application/pdf' : 'application/json';
  return apiFetch(`/api/conversations/${encodedId}/export?format=${encodedFormat}`, {
    method: 'GET',
    headers: {
      Accept: acceptHeader
    }
  });
}

// Legacy export for backward compatibility
export default apiFetch;
