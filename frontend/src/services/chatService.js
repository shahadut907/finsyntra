// Enhanced chat service with EventSource streaming and RAG-empty fallback support
//
// SECURITY: Auth is exclusively via httpOnly cookies (withCredentials: true).
// No tokens are read from localStorage.
import React from 'react';
import { apiFetch, ensureAuthenticatedSession } from '../lib/apiClient';
import { CHAT_STREAM_URL, ENABLE_STREAMING, debugChatLog, redactForLog } from '../config/chat';
import { debugError } from '../config/env';

export class ChatService {
  constructor() {
    this.currentEventSource = null;
    this.sessionId = null;
    this.initialized = false;
    this.streamGeneration = 0;
    this.currentAbort = null;
  }

  // Send a chat message using EventSource GET for streaming
  async sendMessage({
    message,
    sessionId,
    attachments = [],
    useStreaming = ENABLE_STREAMING,
    onToken = null,
    onComplete = null,
    onError = null,
    onInfo = null, // New callback for info messages (like rag_empty)
    signal = null,
    // Server-allowlisted model alias + thinking effort from /api/chat/models.
    model = null,
    effort = null
  }) {
    if (!message.trim()) {
      throw new Error('Message cannot be empty');
    }

    // Guard against sending error strings as queries
    const errorPhrases = [
      'previous request timed out',
      'request failed',
      'error occurred',
      'please try again',
      'connection failed',
      'server error',
      'server took too long',
      'no relevant company docs',
      'please log in',
      'authentication required'
    ];
    const lowerMsg = message.toLowerCase();
    if (errorPhrases.some(phrase => lowerMsg.includes(phrase))) {
      debugChatLog('Blocked error string being sent as query:', message.substring(0, 50));
      throw new Error('Invalid query: error messages cannot be sent');
    }

    // Abort any previous requests
    this.abortCurrentStream();
    const streamGeneration = this.streamGeneration;

    debugChatLog('Sending chat message via EventSource GET:', redactForLog({
      message: message.substring(0, 50) + (message.length > 50 ? '...' : ''),
      sessionId: sessionId || this.sessionId,
      attachments: attachments.length,
      streaming: useStreaming
    }));

    try {
      const result = await this.sendMessageEventSource({
        message,
        sessionId: sessionId || this.sessionId,
        onToken,
        onComplete,
        onError,
        onInfo,
        signal,
        streamGeneration,
        model,
        effort,
      });
      return result;
    } catch (error) {
      debugError('Chat message failed:', error);

      if (error.name === 'AbortError') {
        return { aborted: true, partialResponse: error.partialResponse || '' };
      }

      // Check if this is a CORS error
      if (error.message?.includes('CORS') ||
          error.message?.includes('blocked') ||
          (error.name === 'TypeError' && error.message?.includes('fetch'))) {
        throw new Error('Backend server CORS policy blocks frontend requests. Please configure the backend to allow requests from localhost:3000');
      }

      throw error;
    }
  }

  /**
   * Explain a stream the server refused before it started. Never resends the
   * message: it only reads the (side-effect free) model catalog.
   * Returns an Error, or null to keep the generic message.
   */
  async diagnoseStreamRefusal(model, effort) {
    let response;
    try {
      response = await apiFetch('/api/chat/models');
    } catch {
      return new Error('Connection to server failed. Please try again.');
    }
    if (response.status === 401) return null; // genuinely signed out
    if (!response.ok) return new Error('Connection to server failed. Please try again.');
    const catalog = await response.json().catch(() => null);
    const entry = catalog?.models?.find((m) => m.id === model);
    if (!entry || !entry.available) {
      const err = new Error(`${entry?.label || 'The selected model'} is unavailable right now. Choose another model and resend.`);
      err.code = 'MODEL_UNAVAILABLE';
      return err;
    }
    if (effort && !entry.efforts?.some((e) => e.id === effort)) {
      const err = new Error(`${entry.label} does not support that thinking effort.`);
      err.code = 'INVALID_EFFORT';
      return err;
    }
    return new Error('Connection to server failed. Please try again.');
  }

  // Send message using EventSource GET with SSE
  async sendMessageEventSource({ message, sessionId, onToken, onComplete, onError, onInfo, signal, streamGeneration, model = null, effort = null }) {
    const authenticated = await ensureAuthenticatedSession();
    if (streamGeneration !== undefined && streamGeneration !== this.streamGeneration) {
      const superseded = new Error('Request aborted');
      superseded.name = 'AbortError';
      throw superseded;
    }
    if (!authenticated) {
      const authError = new Error('Authentication expired - please sign in again');
      authError.code = 'AUTH_FAILED';
      onError?.(authError);
      throw authError;
    }

    return new Promise((resolve, reject) => {
      try {
        // SECURITY: Auth is via httpOnly cookies (withCredentials: true on EventSource).
        // No localStorage check needed — the backend enforces authentication.

        // Build URL with query parameters
        const url = new URL(CHAT_STREAM_URL);
        url.searchParams.set('q', message);
        if (sessionId) {
          url.searchParams.set('session_id', sessionId);
        }
        if (model) url.searchParams.set('model', model);
        if (effort) url.searchParams.set('effort', effort);

        // EventSource uses cookies only (no token in URL)
        debugChatLog('EventSource GET request:', redactForLog({
          url: url.toString().substring(0, 100) + '...',
          method: 'GET',
          authVia: 'cookies (withCredentials)'
        }));

        // Create EventSource with credentials for cookie-based auth
        this.currentEventSource = new EventSource(url.toString(), {
          withCredentials: true
        });

        let fullResponse = '';
        let ragStatus = null;
        let sources = [];
        let documentsFound = 0;
        let completion = {};
        let settled = false;
        let diagnosing = false;

        const finishOnce = (result) => {
          if (settled) return;
          settled = true;
          this.currentAbort = null;
          this.closeEventSource();
          onComplete?.(result);
          resolve(result);
        };

        const failOnce = (error) => {
          if (settled) return;
          settled = true;
          this.currentAbort = null;
          this.closeEventSource();
          error.partialResponse = fullResponse;
          onError?.(error);
          reject(error);
        };
        this.currentAbort = () => {
          const abortError = new Error('Request aborted');
          abortError.name = 'AbortError';
          failOnce(abortError);
        };

        this.currentEventSource.onopen = () => {
          debugChatLog('EventSource connection opened');
        };

        this.currentEventSource.onmessage = (event) => {
          try {
            if (event.data === '[DONE]') {
              debugChatLog('EventSource stream completed');
              const result = {
                response: fullResponse,
                text: fullResponse,
                sessionId: this.sessionId,
                sources: sources,
                documentsFound: documentsFound,
                confidence: null,
                metadata: { streamed: true, ragStatus, ...completion },
                fallback: ragStatus === 'empty'
              };
              finishOnce(result);
              return;
            }

            // Parse JSON event data
            try {
              const parsed = JSON.parse(event.data);

              // Handle different event types
              if (parsed.type === 'token') {
                const token = parsed.token ?? parsed.content ?? parsed.delta ?? parsed.text ?? '';
                fullResponse += token;
                onToken?.(token, fullResponse);
              } else if (parsed.type === 'status') {
                onInfo?.({ type: 'status', text: parsed.text });
              } else if (parsed.type === 'rag_status') {
                ragStatus = parsed.value;

                // Notify UI about RAG status (empty or error)
                if (parsed.value === 'empty') {
                  onInfo?.({ message: 'No matching docs found. Using general assistant mode...', code: 'RAG_EMPTY' });
                } else if (parsed.value === 'error') {
                  onInfo?.({ message: 'Document search unavailable. Using general assistant mode...', code: 'RAG_ERROR' });
                }
              } else if (parsed.type === 'complete') {
                sources = parsed.sources || [];
                documentsFound = parsed.documents_found || 0;
                completion = parsed;
              } else if (parsed.type === 'ping') {
                // Heartbeat - keep connection alive
              } else if (parsed.type === 'start' || parsed.type === 'response_start') {
                // Ignore start events
              } else if (parsed.type === 'error') {
                debugError('Stream error event:', parsed.message);
                const errorMsg = parsed.message || 'Stream error occurred';
                failOnce(new Error(errorMsg));
              }
            } catch {
              // Treat as plain text token
              fullResponse += event.data;
              onToken?.(event.data, fullResponse);
            }
          } catch (error) {
            debugError('EventSource message error:', error);
          }
        };

        this.currentEventSource.onerror = (error) => {
          debugError('EventSource error:', error);

          // Check if it's an auth error (EventSource doesn't expose status codes directly)
          // When EventSource gets a 401, it closes immediately
          const isAuthError = this.currentEventSource?.readyState === EventSource.CLOSED;

          const errorMsg = isAuthError
            ? 'Authentication failed - please log in again'
            : 'Connection to server failed. Please try again.';

          const err = new Error(errorMsg);
          if (isAuthError) {
            err.code = 'AUTH_FAILED';
          }

          // EventSource hides the HTTP status, so a request the server refused
          // before streaming (e.g. a model that just became unavailable) looks
          // like an auth failure. Ask the catalog what actually happened rather
          // than resending the message.
          if (isAuthError && model && !diagnosing) {
            diagnosing = true;
            this.closeEventSource();
            this.diagnoseStreamRefusal(model, effort)
              .then((diagnosed) => failOnce(diagnosed || err))
              .catch(() => failOnce(err));
            return;
          }
          if (isAuthError) {
            console.error('❌ EventSource auth error - session may have expired');
          }
          failOnce(err);
        };

        // Handle abort signal
        if (signal) {
          signal.addEventListener('abort', () => {
            const abortError = new Error('Request aborted');
            abortError.name = 'AbortError';
            failOnce(abortError);
          }, { once: true });
        }

      } catch (error) {
        debugChatLog('EventSource setup failed:', error.message);
        reject(error);
      }
    });
  }

  // Close current EventSource connection
  closeEventSource() {
    if (this.currentEventSource) {
      this.currentEventSource.close();
      this.currentEventSource = null;
      debugChatLog('EventSource closed');
    }
  }

  // Deep extractor for assistant text from various unknown response shapes
  extractAssistantTextDeep(input) {
    if (!input) return "";

    // Handle FinSyntra backend format first (highest priority)
    if (input?.success && input?.response) {
      return input.response.trim();
    }

    // Try common direct text fields
    const direct =
      input?.data?.text ??
      input?.text ??
      input?.answer ??
      input?.message ??
      input?.content ??
      input?.output ??
      input?.response ??
      input?.reply ??
      input?.choices?.[0]?.message?.content ??
      input?.choices?.[0]?.text ??
      input?.completion ??
      "";

    if (direct && typeof direct === "string" && direct.trim()) {
      return direct.trim();
    }

    // Handle array of tokens/chunks (streaming data arrays)
    const arrayData = Array.isArray(input) ? input : Array.isArray(input?.data) ? input.data : null;
    if (arrayData?.length) {
      const chunks = arrayData.map(chunk => {
        if (typeof chunk === "string") return chunk;
        return chunk?.token ?? chunk?.delta ?? chunk?.text ?? chunk?.content ?? chunk?.chunk ?? chunk?.message ?? "";
      }).filter(Boolean);

      if (chunks.length > 0) {
        return chunks.join('').trim();
      }
    }

    // Handle ArrayBuffer/Uint8Array (binary responses)
    if (input?.buffer || input instanceof ArrayBuffer || ArrayBuffer.isView(input)) {
      try {
        return new TextDecoder().decode(input).trim();
      } catch (error) {
        debugChatLog('Failed to decode buffer:', error);
      }
    }

    // Handle nested response structures (recursive)
    if (input?.result) {
      return this.extractAssistantTextDeep(input.result);
    }

    if (input?.body) {
      return this.extractAssistantTextDeep(input.body);
    }

    return "";
  }

  // Legacy method for backwards compatibility
  extractAssistantText(json) {
    return this.extractAssistantTextDeep(json);
  }

  // Legacy method for backwards compatibility
  extractResponseText(res) {
    return this.extractAssistantText(res?.data ?? res);
  }

  // Format error messages for user display
  formatErrorMessage(error) {
    if (!navigator.onLine) {
      return 'Network offline';
    }

    if (error.name === 'AbortError') {
      return 'Request cancelled';
    }

    if (error.message?.includes('timeout')) {
      return 'Request timed out';
    }

    if (error.response?.status === 401) {
      return 'Authentication required';
    }

    if (error.response?.status === 403) {
      return 'Access denied';
    }

    if (error.response?.status === 429) {
      return 'Too many requests - please wait';
    }

    if (error.response?.status >= 500) {
      return 'Server error - please try again';
    }

    if (error.message?.includes('CORS')) {
      return 'Connection blocked by security policy';
    }

    // Return a generic but informative message
    return error.message || 'Failed to send message';
  }

  // Abort current streaming request
  abortCurrentStream() {
    this.streamGeneration += 1;
    if (this.currentAbort) {
      this.currentAbort();
    } else {
      this.closeEventSource();
    }
  }

  // Check if currently streaming
  isStreaming() {
    return this.currentEventSource !== null;
  }

  // Set session ID
  setSessionId(sessionId) {
    this.sessionId = sessionId;
    debugChatLog('Session ID updated:', sessionId);
  }

  // Get current session ID
  getSessionId() {
    return this.sessionId;
  }

  // Reset session
  resetSession() {
    this.sessionId = null;
    this.abortCurrentStream();
    debugChatLog('Chat session reset');
  }

  // Upload file helper
  async uploadFile(file) {
    try {
      const formData = new FormData();
      formData.append('file', file);

      debugChatLog('Uploading file:', redactForLog({
        name: file.name,
        size: file.size,
        type: file.type
      }));

      const response = await apiFetch('/api/upload', {
        method: 'POST',
        body: formData,
        // Don't set Content-Type for FormData - browser sets it with boundary
      });

      if (!response.ok) {
        throw new Error(`Upload failed with status ${response.status}`);
      }

      const data = await response.json();

      return {
        id: data.file_id || data.id,
        name: file.name,
        size: file.size,
        type: file.type,
        url: data.url
      };
    } catch (error) {
      debugChatLog('File upload failed:', error);
      throw new Error(this.formatErrorMessage(error));
    }
  }

  // Get conversation history
  async getConversationHistory(sessionId) {
    try {
      const conversationsUrl = `/api/chat/conversations/${sessionId}`;
      debugChatLog('Loading conversation history:', redactForLog({ sessionId, url: conversationsUrl }));

      const response = await apiFetch(conversationsUrl, {
        method: 'GET'
      });

      if (!response.ok) {
        throw new Error(`Failed to load conversation with status ${response.status}`);
      }

      const data = await response.json();
      return data.messages || [];
    } catch (error) {
      debugChatLog('Failed to load conversation history:', error);
      throw new Error(this.formatErrorMessage(error));
    }
  }
}

// Export singleton instance
export const chatService = new ChatService();

// React hook for chat service
export const useChatService = () => {
  const sendMessage = React.useCallback(async (options) => {
    return chatService.sendMessage(options);
  }, []);

  const uploadFile = React.useCallback(async (file) => {
    return chatService.uploadFile(file);
  }, []);

  const abortStream = React.useCallback(() => {
    chatService.abortCurrentStream();
  }, []);

  return {
    sendMessage,
    uploadFile,
    abortStream,
    isStreaming: chatService.isStreaming(),
    sessionId: chatService.getSessionId(),
    setSessionId: chatService.setSessionId.bind(chatService),
    resetSession: chatService.resetSession.bind(chatService)
  };
};

export default chatService;
