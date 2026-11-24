// Minimal network debugging utility for chat diagnostics
export function netlog(tag, data) {
  if (typeof window !== 'undefined' && window.location.search.includes('debug')) {
    console.debug('[FinSyntra]', tag, data);
  }
}

// Helper to redact sensitive data for logging
export function redactLog(obj) {
  if (!obj || typeof obj !== 'object') return obj;
  
  const redacted = { ...obj };
  const sensitiveFields = ['authorization', 'bearer', 'token', 'password', 'secret'];
  
  Object.keys(redacted).forEach(key => {
    const lowerKey = key.toLowerCase();
    if (sensitiveFields.some(field => lowerKey.includes(field))) {
      redacted[key] = '[REDACTED]';
    }
  });
  
  return redacted;
}
