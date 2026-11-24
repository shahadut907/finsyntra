import { useState, useCallback, useEffect, useRef } from 'react';
import { chatService } from '../services/chatService';

const TYPEWRITER_CPS = 30;
const TYPEWRITER_INTERVAL_MS = Math.round(1000 / TYPEWRITER_CPS);

// Keep only the fields the UI may show; the stored record also names the
// provider model, which the chat surface does not display.
const publicModel = (model) => (
  model && typeof model === 'object' && model.alias
    ? { alias: model.alias, label: model.label || model.alias, reasoning_effort: model.reasoning_effort || null }
    : null
);

/**
 * Custom hook for managing chat state and interactions
 * @param {Function} apiCall - API call function for loading conversation history
 * @param {Function} addNotification - Function to show notifications
 * @returns {Object} Chat state and methods
 */
export const useChat = (apiCall, addNotification, options = {}) => {
  const { conversationId, ensureConversationId } = options;
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  
  const bufferRef = useRef('');
  const typewriterTimerRef = useRef(null);
  const finalResultRef = useRef(null);
  const doneRef = useRef(false);
  const statusTextRef = useRef('');
  const displayedTextRef = useRef('');
  const firstTokenRef = useRef(false);
  const skipNextLoadRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      chatService.abortCurrentStream();
      if (typewriterTimerRef.current) clearInterval(typewriterTimerRef.current);
    };
  }, []);

  const loadConversation = useCallback(async (targetConversationId) => {
    if (!targetConversationId) {
      setIsLoading(false);
      setIsStreaming(false);
      setMessages([]);
      return;
    }

    try {
      setIsLoading(false);
      setIsStreaming(false);
      let messagesPayload = [];
      if (apiCall) {
        const response = await apiCall(`/api/conversations/${targetConversationId}`);
        if (!response.ok) {
          throw new Error(`Failed to load conversation (${response.status})`);
        }
        const data = await response.json();
        messagesPayload = Array.isArray(data?.messages) ? data.messages : [];
      } else {
        messagesPayload = await chatService.getConversationHistory(targetConversationId);
      }

      const mappedMessages = messagesPayload.map((message, index) => ({
        id: message.id || `${targetConversationId}_${index}`,
        text: message.content || message.text || '',
        sender: message.message_type === 'user' ? 'user' : 'assistant',
        timestamp: message.timestamp || new Date().toISOString(),
        sources: message.sources || [],
        // Model/effort recorded server-side for this answer (public fields only).
        model: publicModel(message.metadata?.model)
      }));

      if (!mountedRef.current) return;
      setMessages(mappedMessages);
    } catch (error) {
      console.error('Failed to load conversation messages:', error);
      addNotification?.('Failed to load conversation', 'error');
    }
  }, [apiCall, addNotification]);

  useEffect(() => {
    if (!conversationId) {
      chatService.resetSession();
      setIsLoading(false);
      setIsStreaming(false);
      setMessages([]);
      return;
    }

    chatService.setSessionId(conversationId);

    if (skipNextLoadRef.current) {
      skipNextLoadRef.current = false;
      return;
    }

    loadConversation(conversationId);
  }, [conversationId, loadConversation]);

  /**
   * Send a message and handle streaming response
   */
  const sendMessage = useCallback(async (messageText, options = {}) => {
    if (!messageText.trim()) return;

    setIsLoading(true);
    let activeConversationId = conversationId;
    if (!activeConversationId && ensureConversationId) {
      skipNextLoadRef.current = true;
      activeConversationId = await ensureConversationId();
      if (!activeConversationId) {
        skipNextLoadRef.current = false;
      }
    }

    if (!activeConversationId) {
      setIsLoading(false);
      addNotification?.('Unable to start a conversation. Please try again.', 'error');
      return;
    }

    chatService.setSessionId(activeConversationId);

    bufferRef.current = '';
    finalResultRef.current = null;
    doneRef.current = false;
    firstTokenRef.current = false;
    displayedTextRef.current = '';
    statusTextRef.current = 'Thinking...';
    if (typewriterTimerRef.current) {
      clearInterval(typewriterTimerRef.current);
      typewriterTimerRef.current = null;
    }
    
    // Add user message
    const userMessage = {
      id: Date.now(),
      text: messageText,
      sender: 'user',
      timestamp: new Date().toISOString(),
    };
    
    setMessages(prev => [...prev, userMessage]);

    // Create assistant message placeholder
    const assistantMessageId = Date.now() + 1;
    const assistantMessage = {
      id: assistantMessageId,
      text: '',
      sender: 'assistant',
      timestamp: new Date().toISOString(),
      isStreaming: true,
      statusText: statusTextRef.current
    };
    
    setMessages(prev => [...prev, assistantMessage]);
    setIsStreaming(true);

    const finalizeIfDone = () => {
      if (!mountedRef.current) return;
      if (doneRef.current && !bufferRef.current) {
        if (typewriterTimerRef.current) {
          clearInterval(typewriterTimerRef.current);
          typewriterTimerRef.current = null;
        }
        const result = finalResultRef.current || {};
        const generationFailed = result.metadata?.success === false ||
          ['timeout', 'unavailable', 'rate_limited', 'malformed', 'error'].includes(result.metadata?.generation_status);
        setMessages(prev => prev.map(msg =>
          msg.id === assistantMessageId
                ? {
                    ...msg,
                    text: result.response || result.text || msg.text,
                    isStreaming: false,
                    sources: result.sources,
                    confidence: result.confidence,
                    // The model the server reports actually ran (absent for
                    // canned replies where no model generated text).
                    model: publicModel(result.metadata?.model),
                    isError: generationFailed,
                    // String error lets the ErrorChip (with retry) render.
                    error: generationFailed
                      ? (result.metadata?.error_message || 'Answer generation failed')
                      : undefined,
                    isInformational: result.fallback === true,
                statusText: result.metadata?.generation_status === 'rate_limited'
                  ? 'Demo capacity reached. Please try again shortly.'
                  : generationFailed ? 'Answer generation failed' : ''
              }
            : msg
        ));
        setIsStreaming(false);
        setIsLoading(false);
      }
    };

    // Ticks reveal a backlog-proportional number of characters, not a fixed
    // one-per-tick. A short, freshly-arrived buffer still reveals one
    // character at a time (the typewriter feel), but once the backend has
    // already delivered a long or complete response (long answers, or the
    // whole remainder dumped into bufferRef on completion — see onComplete
    // below), the reveal accelerates to catch up within ~2.5s instead of
    // lagging behind the already-available text at a flat 30 chars/sec. This
    // only paces the client-side redraw of text already received; it never
    // changes when the backend actually finishes generating.
    const MAX_CATCH_UP_TICKS = 75;
    const startTypewriter = () => {
      if (typewriterTimerRef.current) return;
      typewriterTimerRef.current = setInterval(() => {
        if (!mountedRef.current) return;
        if (!bufferRef.current) {
          finalizeIfDone();
          return;
        }
        const charsThisTick = Math.max(
          1,
          Math.ceil(bufferRef.current.length / MAX_CATCH_UP_TICKS)
        );
        const nextChunk = bufferRef.current.slice(0, charsThisTick);
        bufferRef.current = bufferRef.current.slice(charsThisTick);
        setMessages(prev => prev.map(msg => {
          if (msg.id !== assistantMessageId) return msg;
          const nextText = `${msg.text || ''}${nextChunk}`;
          displayedTextRef.current = nextText;
          return {
            ...msg,
            text: nextText,
            isStreaming: true
          };
        }));
      }, TYPEWRITER_INTERVAL_MS);
    };

    // chatService resolves on deliberate abort (onError already finalized
    // the message); it rethrows other failures after onError ran.
    let streamErrorHandled = false;
    try {
      // Use chatService to send message with streaming
      await chatService.sendMessage({
        message: messageText,
        model: options.model || null,
        effort: options.effort || null,
        onToken: (token, fullText) => {
          if (!firstTokenRef.current) {
            firstTokenRef.current = true;
            statusTextRef.current = '';
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, statusText: '' }
                : msg
            ));
          }
          bufferRef.current += token;
          startTypewriter();
          
          // Call custom onToken callback if provided
          options.onToken?.(token, fullText);
        },
        onComplete: (result) => {
          const normalizedResult = typeof result === 'string' ? { response: result } : (result || {});
          finalResultRef.current = normalizedResult;
          doneRef.current = true;
          const targetText = normalizedResult.response || normalizedResult.text || '';
          const pendingLength = displayedTextRef.current.length + bufferRef.current.length;
          if (targetText && pendingLength < targetText.length) {
            bufferRef.current += targetText.slice(pendingLength);
          }
          startTypewriter();
          
          // Call custom onComplete callback if provided
          options.onComplete?.(normalizedResult);
        },
        onError: (error) => {
          console.error('Chat error:', error);
          streamErrorHandled = true;
          if (typewriterTimerRef.current) {
            clearInterval(typewriterTimerRef.current);
            typewriterTimerRef.current = null;
          }
          
          const wasStopped = error.name === 'AbortError';
          // Preserve useful partial output and visibly mark a failed turn. A
          // deliberate stop is not presented as a server failure.
          setMessages(prev => prev.map(msg => msg.id === assistantMessageId
            ? { ...msg, text: error.partialResponse || msg.text, isStreaming: false, isError: !wasStopped, error: wasStopped ? undefined : (error.message || 'Response interrupted'), statusText: wasStopped ? 'Stopped' : 'Response interrupted' }
            : msg));
          
          setIsStreaming(false);
          setIsLoading(false);
          
          // Show error notification
          if (!wasStopped) {
            addNotification?.(
              error.message || 'Failed to send message. Please try again.',
              'error'
            );
          }
          
          // Call custom onError callback if provided
          options.onError?.(error);
        },
        onInfo: (info) => {
          if (info?.type === 'status') {
            statusTextRef.current = info.text || 'Thinking...';
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, statusText: statusTextRef.current }
                : msg
            ));
            return;
          }
          const infoMessage = typeof info === 'string' ? info : info?.message;
          // Show info notification (e.g., "No RAG documents found")
          if (infoMessage) {
            addNotification?.(infoMessage, 'info');
          }
          
          // Call custom onInfo callback if provided
          options.onInfo?.(info);
        }
      });
    } catch (error) {
      // Abort and already-surfaced stream errors were finalized in onError;
      // only truly unexpected throw paths land here.
      if (streamErrorHandled || error?.name === 'AbortError') {
        return;
      }
      console.error('Unexpected error in sendMessage:', error);
      if (typewriterTimerRef.current) {
        clearInterval(typewriterTimerRef.current);
        typewriterTimerRef.current = null;
      }
      
      setMessages(prev => prev.map(msg => msg.id === assistantMessageId
        ? { ...msg, isStreaming: false, isError: true, error: 'Response interrupted', statusText: 'Response interrupted' }
        : msg));
      
      setIsStreaming(false);
      setIsLoading(false);
      
      addNotification?.(
        'An unexpected error occurred. Please try again.',
        'error'
      );
    }
  }, [addNotification, conversationId, ensureConversationId]);

  /**
   * Retry the last failed message
   */
  // ``sendOptions`` (model/effort) is supplied by the caller so a retry uses
  // the selection the user currently sees, never a hidden substitute.
  const retryMessage = useCallback(async (sendOptions = {}) => {
    // Find the last user message
    const lastUserMessage = [...messages]
      .reverse()
      .find(msg => msg.sender === 'user');
    
    if (lastUserMessage) {
      // Drop the failed turn (user message + partial answer) entirely so the
      // resent message is not duplicated in the transcript.
      setMessages(prev => prev.filter(msg =>
        msg.timestamp < lastUserMessage.timestamp
      ));

      // Resend the message
      await sendMessage(lastUserMessage.text, sendOptions && typeof sendOptions === 'object' ? sendOptions : {});
    }
  }, [messages, sendMessage]);

  /**
   * Abort current streaming
   */
  const abortStreaming = useCallback(() => {
    chatService.abortCurrentStream();
    setIsStreaming(false);
    setIsLoading(false);
    if (typewriterTimerRef.current) {
      clearInterval(typewriterTimerRef.current);
      typewriterTimerRef.current = null;
    }
    
    // Mark the last assistant message as complete
    setMessages(prev => prev.map((msg, idx) => 
      idx === prev.length - 1 && msg.sender === 'assistant'
        ? { ...msg, isStreaming: false }
        : msg
    ));
    
    addNotification?.('Message generation stopped', 'info');
  }, [addNotification]);

  return {
    messages,
    sendMessage,
    retryMessage,
    isLoading,
    isStreaming,
    abortStreaming
  };
};

export default useChat;

