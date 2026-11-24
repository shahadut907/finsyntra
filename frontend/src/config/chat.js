// Centralized chat endpoint configuration with autodiscovery support
import { debugLog } from './env';

// REGRESSION FIX 2025-10-09: webpack-compatible env getter
const getEnv = (k, d = null) => 
  (typeof process !== "undefined" ? process.env[k] : undefined) ??
  (typeof window !== "undefined" ? window.__ENV?.[k] : undefined) ?? d;

// Helper to normalize URLs and avoid double slashes
export const normalizeUrl = (...parts) => {
  return parts
    .filter(Boolean)
    .map((part, index) => {
      // Remove leading slash from non-first parts
      if (index > 0 && part.startsWith('/')) {
        part = part.slice(1);
      }
      // Remove trailing slash from non-last parts
      if (index < parts.length - 1 && part.endsWith('/')) {
        part = part.slice(0, -1);
      }
      return part;
    })
    .join('/');
};

// Resolve environment variables with precedence (first found wins)
const getEnvVar = (patterns) => {
  for (const pattern of patterns) {
    // Next.js pattern
    if (getEnv(`NEXT_PUBLIC_${pattern}`)) {
      return getEnv(`NEXT_PUBLIC_${pattern}`);
    }
    
    // Vite pattern
    if (getEnv(`VITE_${pattern}`)) {
      return getEnv(`VITE_${pattern}`);
    }
    
    // Create React App pattern
    if (getEnv(`REACT_APP_${pattern}`)) {
      return getEnv(`REACT_APP_${pattern}`);
    }
  }
  return null;
};

// Resolve chat base URL
const getChatBase = () => {
  // Try environment variables first
  const envBase = getEnvVar(['API_BASE_URL', 'API_URL']);
  if (envBase) return envBase;
  
  // Try legacy React App pattern
  if (process.env.REACT_APP_API_URL) {
    return process.env.REACT_APP_API_URL;
  }
  
  // In development, always use backend port 8000, not frontend port 3000
  if (process.env.NODE_ENV === 'development') {
    return 'http://localhost:8000';
  }
  
  // In production, fallback to current origin
  return typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000';
};

// Chat configuration with environment variable support
export const CHAT_BASE = getChatBase();

export const CHAT_URL = 
  getEnvVar(['CHAT_URL']) || 
  normalizeUrl(CHAT_BASE, '/api/chat');

export const CHAT_STREAM_URL = 
  getEnvVar(['CHAT_STREAM_URL']) || 
  normalizeUrl(CHAT_BASE, '/api/chat/stream');

export const CHAT_STREAM_METHOD = getEnvVar(['CHAT_STREAM_METHOD']) || 'POST'; // Default to POST for streaming endpoint

export const ENABLE_STREAMING = (() => {
  const value = getEnvVar(['ENABLE_STREAMING']);
  if (value === 'false' || value === '0') return false;
  // Enable streaming with auto-fallback to JSON for FinSyntra backend compatibility
  return true; // Now supports both streaming and JSON fallback
})();

// Health endpoint
export const HEALTH_URL = normalizeUrl(CHAT_BASE, '/health');

// Upload endpoint  
export const UPLOAD_URL = normalizeUrl(CHAT_BASE, '/api/upload');

// Result polling URL for non-immediate responses
export const CHAT_RESULT_URL = 
  getEnvVar(['CHAT_RESULT_URL']) || 
  normalizeUrl(CHAT_BASE, '/api/chat/result');

// Debug logging helper
export const debugChatLog = (...args) => {
  if (typeof window !== 'undefined' && window.location.search.includes('debug=net')) {
    console.log('[FinSyntra Chat]', ...args);
  } else {
    debugLog('[Chat]', ...args);
  }
};

// Redact sensitive information from logs
export const redactForLog = (obj) => {
  if (!obj || typeof obj !== 'object') return obj;
  
  const redacted = { ...obj };
  
  // Redact common sensitive fields
  const sensitiveFields = ['token', 'authorization', 'password', 'secret', 'key'];
  
  Object.keys(redacted).forEach(key => {
    const lowerKey = key.toLowerCase();
    if (sensitiveFields.some(field => lowerKey.includes(field))) {
      redacted[key] = '[REDACTED]';
    }
  });
  
  return redacted;
};

// Configuration summary for debugging
export const getChatConfig = () => ({
  chatBase: CHAT_BASE,
  chatUrl: CHAT_URL,
  chatStreamUrl: CHAT_STREAM_URL,
  chatStreamMethod: CHAT_STREAM_METHOD,
  chatResultUrl: CHAT_RESULT_URL,
  enableStreaming: ENABLE_STREAMING,
  healthUrl: HEALTH_URL,
  uploadUrl: UPLOAD_URL
});

// Log configuration on module load (development only)
if (process.env.NODE_ENV === 'development') {
  debugChatLog('Chat configuration:', redactForLog(getChatConfig()));
}
