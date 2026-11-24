import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import AppShell from './layout/AppShell';
import DarkChatInterface from './DarkChatInterface';

export const ChatPage = ({
  user,
  darkMode,
  apiCall,
  addNotification,
  authToken,
  onLogout
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  // Prompt handed over from the home page (category pill / composer).
  const initialPrompt = location.state?.initialPrompt;
  // "New conversation" pressed from another page lands here with this flag.
  const wantsNewConversation = Boolean(location.state?.newConversation);
  const newConversationHandledRef = useRef(false);
  const [conversations, setConversations] = useState([]);
  const [isLoadingConversations, setIsLoadingConversations] = useState(false);
  const [currentConversationId, setCurrentConversationId] = useState(null);

  const loadConversations = useCallback(async (showNotification = false) => {
    try {
      setIsLoadingConversations(true);
      const response = await apiCall('/api/conversations');
      if (!response.ok) {
        throw new Error(`Failed to load conversations (${response.status})`);
      }
      const data = await response.json();
      const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
      setConversations(sessions);
      setCurrentConversationId(current => current || sessions[0]?.id || null);
      if (showNotification) {
        addNotification('Conversation history refreshed', 'success');
      }
    } catch (error) {
      console.error('Failed to load conversations:', error);
      addNotification('Failed to load conversation history', 'error');
    } finally {
      setIsLoadingConversations(false);
    }
  }, [apiCall, addNotification]);

  const createConversation = useCallback(async () => {
    try {
      const response = await apiCall('/api/conversations', {
        method: 'POST',
        body: JSON.stringify({})
      });
      if (!response.ok) {
        throw new Error(`Failed to create conversation (${response.status})`);
      }
      const data = await response.json();
      const newId = data?.id;
      if (!newId) {
        throw new Error('Missing conversation id');
      }
      setCurrentConversationId(newId);
      setConversations(prev => {
        const next = [
          {
            id: newId,
            session_name: data.title,
            created_at: data.created_at,
            updated_at: data.updated_at,
            message_count: 0
          },
          ...prev
        ];
        const seen = new Set();
        return next.filter(item => {
          if (!item?.id || seen.has(item.id)) return false;
          seen.add(item.id);
          return true;
        });
      });
      return newId;
    } catch (error) {
      console.error('Failed to create conversation:', error);
      addNotification('Failed to start a new conversation', 'error');
      return null;
    }
  }, [apiCall, addNotification]);

  const ensureConversationId = useCallback(async () => {
    if (currentConversationId) return currentConversationId;
    return await createConversation();
  }, [currentConversationId, createConversation]);

  const handleSelectConversation = (conversationId) => {
    setCurrentConversationId(conversationId);
  };

  const handleNewConversation = useCallback(async () => {
    // The new, empty conversation opening is the feedback; failures are
    // reported by createConversation().
    await createConversation();
  }, [createConversation]);

  // Refresh the sidebar titles/counts quietly after a turn completes.
  const handleConversationActivity = useCallback(() => {
    loadConversations(false);
  }, [loadConversations]);


  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (!wantsNewConversation || newConversationHandledRef.current) return;
    newConversationHandledRef.current = true;
    // Clear the flag first so a reload or back-navigation does not repeat it.
    navigate(location.pathname, { replace: true, state: null });
    handleNewConversation();
  }, [wantsNewConversation, navigate, location.pathname, handleNewConversation]);

  const currentConversation = conversations.find(c => c.id === currentConversationId);
  const conversationTitle = currentConversation?.session_name || currentConversation?.title || 'New conversation';

  return (
    <div className={darkMode ? 'dark' : ''}>
      <AppShell
        user={user}
        title={conversationTitle}
        onLogout={onLogout}
        onNewConversation={handleNewConversation}
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onRefreshConversations={() => loadConversations(true)}
        isLoadingConversations={isLoadingConversations}
      >
        <DarkChatInterface
          user={user}
          apiCall={apiCall}
          addNotification={addNotification}
          authToken={authToken}
          conversationId={currentConversationId}
          ensureConversationId={ensureConversationId}
          initialPrompt={initialPrompt}
          onConversationActivity={handleConversationActivity}
        />
      </AppShell>
    </div>
  );
};

export default ChatPage;
