import axios from 'axios';
import { API_BASE_URL, API_TIMEOUT, ENDPOINTS, debugLog, debugError } from '../config/env';

// Auth debugging helper
const authDebugLog = (tag, data) => {
  if (typeof window !== 'undefined' && window.location.search.includes('debug=auth')) {
    const redacted = { ...data };
    // Redact sensitive auth data
    if (redacted.hasAuthHeader) {
      redacted.authHeader = '[REDACTED]';
    }
    console.debug('[FinSyntra] auth', tag, redacted);
  }
};

// Create axios instance with base configuration
// SECURITY: Auth is exclusively via httpOnly cookies (withCredentials: true).
// No tokens are read from or written to localStorage.
export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true, // Enable cookies for auth
  timeout: API_TIMEOUT, // Configurable timeout from env
  headers: {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
  },
});

let isRefreshing = false;
let failedQueue = [];

const processQueue = (error, token = null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  
  failedQueue = [];
};

// Retry logic for server errors with exponential backoff
const retryRequest = async (config, retryCount = 0) => {
  const maxRetries = 3;
  const baseDelay = 300; // Base delay in ms
  
  if (retryCount >= maxRetries) {
    throw new Error('Maximum retry attempts exceeded');
  }
  
  // Check if we're offline
  if (!navigator.onLine) {
    throw new Error('Network offline');
  }
  
  // Exponential backoff: 300ms, 900ms, 1500ms
  const delay = baseDelay * (retryCount + 1) + (retryCount * 600);
  
  debugLog(`Retrying request (attempt ${retryCount + 1}/${maxRetries}) after ${delay}ms delay`);
  
  await new Promise(resolve => setTimeout(resolve, delay));
  
  try {
    return await api(config);
  } catch (error) {
    // Only retry on 5xx errors or network errors
    if (shouldRetry(error)) {
      return retryRequest(config, retryCount + 1);
    }
    throw error;
  }
};

// Determine if an error should trigger a retry
const shouldRetry = (error) => {
  // Don't retry auth errors
  if (error.response?.status === 401 || error.response?.status === 403) {
    return false;
  }
  
  // Retry on 5xx server errors
  if (error.response?.status >= 500) {
    return true;
  }
  
  // Retry on network errors (no response)
  if (!error.response && error.code !== 'EABORT') {
    return true;
  }
  
  return false;
};

// Request interceptor — add CSRF token and debug logging
// SECURITY: No Bearer token is attached. Auth is via httpOnly cookies.
api.interceptors.request.use(
  (config) => {
    // Add CSRF token if available
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                      document.cookie.split(';').find(c => c.trim().startsWith('csrf='))?.split('=')[1];
    if (csrfToken) {
      config.headers['X-CSRF-Token'] = csrfToken;
    }
    
    // Ensure credentials are included for all requests
    config.withCredentials = true;
    
    // Auth debugging
    authDebugLog('REQUEST', {
      url: config.url,
      method: config.method?.toUpperCase(),
      authMethod: 'cookies only (httpOnly)',
      withCredentials: config.withCredentials,
      hasCsrfToken: !!csrfToken
    });
    
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for automatic token refresh and retries
api.interceptors.response.use(
  (response) => {
    debugLog(`API Success: ${response.config.method?.toUpperCase()} ${response.config.url} -> ${response.status}`);
    return response;
  },
  async (error) => {
    const originalRequest = error.config;
    
    debugError(`API Error: ${originalRequest.method?.toUpperCase()} ${originalRequest.url} ->`, error.response?.status || 'Network Error');
    
    // Handle 401 (authentication) errors with token refresh
    if (error.response?.status === 401 && !originalRequest._retry) {
      // Skip refresh for auth endpoints to prevent loops
      if (originalRequest.url?.includes('/auth/login') || originalRequest.url?.includes('/auth/refresh')) {
        return Promise.reject(error);
      }

      if (isRefreshing) {
        // If already refreshing, queue the request
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then(() => {
          // Retry with cookies (no Bearer needed)
          return api(originalRequest);
        }).catch(err => {
          return Promise.reject(err);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        debugLog('🔄 Session expired, attempting cookie-based refresh...');
        const response = await axios.post(`${API_BASE_URL}${ENDPOINTS.AUTH_REFRESH}`, {}, {
          withCredentials: true
        });
        
        if (response.data) {
          debugLog('✅ Token refreshed successfully (new cookie set by backend)');
          processQueue(null);
          
          // Retry original request — cookies are automatically sent
          return api(originalRequest);
        }
      } catch (refreshError) {
        debugError('❌ Token refresh failed:', refreshError);
        processQueue(refreshError, null);
        
        // Legacy cleanup — remove any leftover keys from prior versions
        localStorage.removeItem('finsolve_auth_token');
        localStorage.removeItem('finsolve_user_data');
        
        // Trigger logout via custom event
        window.dispatchEvent(new CustomEvent('auth:logout', { 
          detail: { reason: 'refresh_failed' } 
        }));
        
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    // Handle retryable errors (5xx, network issues)
    if (shouldRetry(error) && !originalRequest._retryAttempt) {
      originalRequest._retryAttempt = true;
      
      try {
        return await retryRequest(originalRequest);
      } catch (retryError) {
        // If retry also fails, return the original error
        debugError('❌ All retry attempts failed');
        return Promise.reject(error);
      }
    }

    return Promise.reject(error);
  }
);

// Unified fetch wrapper for streaming and other non-axios requests
// SECURITY: Auth is via httpOnly cookies. No Bearer token attached.
export const authenticatedFetch = async (url, options = {}) => {
  // Get CSRF token if available
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                    document.cookie.split(';').find(c => c.trim().startsWith('csrf='))?.split('=')[1];
  
  // Prepare headers
  const headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    ...options.headers
  };
  
  if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  
  // Ensure credentials and CORS
  const fetchOptions = {
    credentials: 'include',
    mode: 'cors',
    ...options,
    headers
  };
  
  // Auth debugging
  authDebugLog('FETCH_REQUEST', {
    url: url,
    method: fetchOptions.method || 'GET',
    authMethod: 'cookies only (httpOnly)',
    withCredentials: fetchOptions.credentials === 'include',
    hasCsrfToken: !!csrfToken
  });
  
  return fetch(url, fetchOptions);
};

export default api;
