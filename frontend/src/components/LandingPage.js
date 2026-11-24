import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AppShell from './layout/AppShell';
import Hero from './Hero';
import PromptComposer from './PromptComposer';

export const LandingPage = ({
  user,
  onLogout,
  onSendMessage,
  addNotification
}) => {
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(false);

  const handleCategorySelect = (category) => {
    // Hand the prompt to the chat composer via router state.
    const prompts = {
      finance: 'Summarize the key figures from the latest quarterly report',
      hr: 'Summarize our leave policy from the HR documents',
      leadership: 'Give me an executive snapshot of this quarter'
    };

    const message = prompts[category.id] || category.description;
    navigate('/chat', { state: { initialPrompt: message } });
  };

  const handleSendMessage = async (message) => {
    if (!message.trim()) return;

    try {
      setIsLoading(true);

      // Call the existing send message function from parent
      if (onSendMessage) {
        await onSendMessage(message);
      }

      // Navigate to chat page with the composer pre-filled
      navigate('/chat', { state: { initialPrompt: message } });

    } catch (error) {
      console.error('Failed to send message:', error);
      if (addNotification) {
        addNotification('Failed to send message. Please try again.', 'error');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AppShell
      user={user}
      title="Home"
      onLogout={onLogout}
    >
      <Hero
        user={user}
        onCategorySelect={handleCategorySelect}
      />
      <PromptComposer
        onSendMessage={handleSendMessage}
        isLoading={isLoading}
      />
    </AppShell>
  );
};

export default LandingPage;
