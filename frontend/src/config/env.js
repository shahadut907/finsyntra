// Centralized environment configuration
// Supports multiple bundler patterns: Next.js, Vite, Create React App

// REGRESSION FIX 2025-10-09: webpack-compatible env getter
const getEnv = (k, d = null) => 
  (typeof process !== "undefined" ? process.env[k] : undefined) ??
  (typeof window !== "undefined" ? window.__ENV?.[k] : undefined) ?? d;

// Detect and resolve API base URL from different env patterns
const getApiBaseUrl = () => {
  // Next.js pattern
  if (getEnv('NEXT_PUBLIC_API_BASE_URL')) {
    return getEnv('NEXT_PUBLIC_API_BASE_URL');
  }
  
  // Vite pattern
  if (getEnv('VITE_API_BASE_URL')) {
    return getEnv('VITE_API_BASE_URL');
  }
  
  // Create React App pattern
  if (getEnv('REACT_APP_API_BASE_URL')) {
    return getEnv('REACT_APP_API_BASE_URL');
  }
  
  // Legacy pattern (current)
  if (getEnv('REACT_APP_API_URL')) {
    return getEnv('REACT_APP_API_URL');
  }

  // No build-time override. Development targets the local backend on 8000;
  // any other build (production, or NODE_ENV unset) must never guess a
  // visitor's localhost — same-origin is the only safe default, matching
  // lib/apiClient.js and config/chat.js.
  if (process.env.NODE_ENV === 'development') {
    return 'http://localhost:8000';
  }
  return typeof window !== 'undefined' ? window.location.origin : '';
};

// Feature flags with environment variable support
const getFeatureFlag = (flag, defaultValue = false) => {
  const envValue = 
    getEnv(`NEXT_PUBLIC_${flag}`) || 
    getEnv(`VITE_${flag}`) ||
    getEnv(`REACT_APP_${flag}`);
    
  if (envValue === undefined) return defaultValue;
  
  // Handle boolean strings
  if (envValue === 'true' || envValue === '1') return true;
  if (envValue === 'false' || envValue === '0') return false;
  
  return envValue;
};

// Environment detection
const isDevelopment = process.env.NODE_ENV === 'development';
const isProduction = process.env.NODE_ENV === 'production';

// Export configuration
export const API_BASE_URL = getApiBaseUrl();
export const ENABLE_STREAMING = getFeatureFlag('ENABLE_STREAMING', true);
export const USE_FALLBACK_RESPONSES = getFeatureFlag('USE_FALLBACK_RESPONSES', false);
export const ENABLE_DEBUG_LOGGING = getFeatureFlag('ENABLE_DEBUG_LOGGING', isDevelopment);
export const API_TIMEOUT = parseInt(getFeatureFlag('API_TIMEOUT', '30000'), 10);

// API Endpoints - centralized endpoint management
export const ENDPOINTS = {
  HEALTH: '/health',
  CHAT: '/api/chat',
  CHAT_STREAM: '/api/chat/stream',
  AUTH_LOGIN: '/auth/login',
  AUTH_REFRESH: '/auth/refresh',
  AUTH_LOGOUT: '/auth/logout',
  UPLOAD: '/api/upload',
  CONVERSATIONS: '/api/conversations'
};

// Debug helpers
export const debugLog = (...args) => {
  if (ENABLE_DEBUG_LOGGING) {
    console.log('[FinSyntra Debug]', ...args);
  }
};

export const debugError = (...args) => {
  if (ENABLE_DEBUG_LOGGING) {
    console.error('[FinSyntra Error]', ...args);
  }
};

// Environment info (for debugging)
export const ENV_INFO = {
  isDevelopment,
  isProduction,
  apiBaseUrl: API_BASE_URL,
  enableStreaming: ENABLE_STREAMING,
  useFallbackResponses: USE_FALLBACK_RESPONSES,
  apiTimeout: API_TIMEOUT
};

const config = {
  API_BASE_URL,
  ENABLE_STREAMING,
  USE_FALLBACK_RESPONSES,
  ENABLE_DEBUG_LOGGING,
  API_TIMEOUT,
  ENDPOINTS,
  debugLog,
  debugError,
  ENV_INFO
};

export default config;
