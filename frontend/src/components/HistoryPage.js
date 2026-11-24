import React from 'react';
import { useNavigate } from 'react-router-dom';
import AppShell from './layout/AppShell';
import ConversationMemory from './ConversationMemory';

export const HistoryPage = ({
  user,
  darkMode,
  apiCall,
  addNotification,
  onLogout
}) => {
  const navigate = useNavigate();

  return (
    <div className={darkMode ? 'dark' : ''}>
      <AppShell
        user={user}
        title="Conversation history"
        subtitle="Browse, review and manage your saved conversations"
        onLogout={onLogout}
      >
        <ConversationMemory
          embedded
          isOpen={true}
          onClose={() => navigate('/chat')}
          darkMode={darkMode}
          user={user}
          apiCall={apiCall}
          addNotification={addNotification}
          enableExportAll={false}
        />
      </AppShell>
    </div>
  );
};

export default HistoryPage;
