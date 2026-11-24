// Streaming support for real-time chat responses
import React from 'react';
import { API_BASE_URL, ENDPOINTS, ENABLE_STREAMING, debugLog, debugError } from '../config/env';

// Server-Sent Events streaming for chat responses
export class ChatStream {
  constructor() {
    this.controller = null;
    this.isStreaming = false;
  }

  // Start streaming chat response
  async streamChat({ message, sessionId, onToken, onComplete, onError, signal }) {
    if (!ENABLE_STREAMING) {
      throw new Error('Streaming is disabled');
    }

    this.isStreaming = true;
    this.controller = signal || new AbortController();

    try {
      debugLog('Starting chat stream for message:', message.substring(0, 50) + '...');

      // SECURITY: Auth is via httpOnly cookies (credentials: 'include').
      // No Bearer token from localStorage.
      const response = await fetch(`${API_BASE_URL}${ENDPOINTS.CHAT_STREAM}`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({
          message,
          session_id: sessionId,
          stream: true
        }),
        signal: this.controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      if (!response.body) {
        throw new Error('ReadableStream not supported');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullResponse = '';

      while (this.isStreaming) {
        const { done, value } = await reader.read();
        
        if (done) break;

        // Decode the chunk and add to buffer
        buffer += decoder.decode(value, { stream: true });
        
        // Process complete lines
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          if (!line.trim()) continue;
          
          try {
            // Handle Server-Sent Events format
            if (line.startsWith('data: ')) {
              const data = line.slice(6);
              
              if (data === '[DONE]') {
                debugLog('Stream completed');
                onComplete?.(fullResponse);
                return fullResponse;
              }

              // Try to parse as JSON for structured data
              try {
                const parsed = JSON.parse(data);
                if (parsed.token) {
                  fullResponse += parsed.token;
                  onToken?.(parsed.token, fullResponse);
                } else if (parsed.content) {
                  fullResponse += parsed.content;
                  onToken?.(parsed.content, fullResponse);
                }
              } catch {
                // Treat as plain text token
                fullResponse += data;
                onToken?.(data, fullResponse);
              }
            }
          } catch (error) {
            debugError('Error processing stream line:', error);
          }
        }
      }

      return fullResponse;

    } catch (error) {
      debugError('Chat stream error:', error);
      
      if (error.name === 'AbortError') {
        debugLog('Chat stream aborted');
        return null;
      }
      
      onError?.(error);
      throw error;
    } finally {
      this.isStreaming = false;
      this.controller = null;
    }
  }

  // Stop the current stream
  abort() {
    if (this.controller) {
      this.controller.abort();
      this.isStreaming = false;
      debugLog('Chat stream aborted by user');
    }
  }

  // Check if currently streaming
  getIsStreaming() {
    return this.isStreaming;
  }
}

// Fallback streaming using EventSource (for servers that prefer this approach)
export class EventSourceStream {
  constructor() {
    this.eventSource = null;
    this.isStreaming = false;
  }

  async streamChat({ message, sessionId, onToken, onComplete, onError }) {
    if (!ENABLE_STREAMING) {
      throw new Error('Streaming is disabled');
    }

    this.isStreaming = true;
    let fullResponse = '';

    try {
      debugLog('Starting EventSource stream for message:', message.substring(0, 50) + '...');

      // SECURITY: Auth is via httpOnly cookies.
      // Do NOT pass tokens in URL — that exposes them in server logs.
      const url = new URL(`${API_BASE_URL}${ENDPOINTS.CHAT_STREAM}`);
      url.searchParams.set('message', message);
      url.searchParams.set('session_id', sessionId || '');

      // Use EventSource with credentials (cookies sent automatically)
      this.eventSource = new EventSource(url.toString(), {
        withCredentials: true
      });

      return new Promise((resolve, reject) => {
        this.eventSource.onmessage = (event) => {
          try {
            if (event.data === '[DONE]') {
              debugLog('EventSource stream completed');
              this.close();
              onComplete?.(fullResponse);
              resolve(fullResponse);
              return;
            }

            // Try to parse as JSON, fallback to plain text
            let token;
            try {
              const parsed = JSON.parse(event.data);
              token = parsed.token || parsed.content || event.data;
            } catch {
              token = event.data;
            }

            fullResponse += token;
            onToken?.(token, fullResponse);
          } catch (error) {
            debugError('EventSource message error:', error);
          }
        };

        this.eventSource.onerror = (error) => {
          debugError('EventSource error:', error);
          
          // Check if it's a 401 error (connection refused/unauthorized)
          if (this.eventSource.readyState === EventSource.CLOSED) {
            debugError('EventSource closed - possibly due to auth error');
          }
          
          this.close();
          const err = new Error('EventSource connection failed - please check authentication');
          onError?.(err);
          reject(err);
        };

        this.eventSource.onopen = () => {
          debugLog('EventSource connection opened');
        };
      });

    } catch (error) {
      debugError('EventSource stream error:', error);
      this.close();
      onError?.(error);
      throw error;
    }
  }

  close() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
      this.isStreaming = false;
      debugLog('EventSource stream closed');
    }
  }

  getIsStreaming() {
    return this.isStreaming;
  }
}

// Factory function to create appropriate stream based on server capabilities
export const createChatStream = (preferEventSource = false) => {
  if (preferEventSource) {
    return new EventSourceStream();
  }
  return new ChatStream();
};

// React hook for chat streaming
export const useChatStream = (preferEventSource = false) => {
  const streamRef = React.useRef(null);
  
  React.useEffect(() => {
    streamRef.current = createChatStream(preferEventSource);
    
    return () => {
      if (streamRef.current) {
        streamRef.current.abort?.();
        streamRef.current.close?.();
      }
    };
  }, [preferEventSource]);

  const startStream = React.useCallback(async (options) => {
    return streamRef.current?.streamChat(options);
  }, []);

  const stopStream = React.useCallback(() => {
    streamRef.current?.abort?.();
    streamRef.current?.close?.();
  }, []);

  const isStreaming = streamRef.current?.getIsStreaming() || false;

  return {
    startStream,
    stopStream,
    isStreaming
  };
};

export default ChatStream;
