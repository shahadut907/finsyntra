import React, { useState } from 'react';
import ChatComposer from './chat/ChatComposer';

export const PromptComposer = ({
  onSendMessage,
  isLoading = false,
  placeholder = 'Ask a question about your documents'
}) => {
  const [inputValue, setInputValue] = useState('');

  const handleSubmit = async () => {
    if (!inputValue.trim() || isLoading) return;

    const message = inputValue.trim();
    setInputValue('');

    // Call the parent's send message handler
    await onSendMessage(message);
  };

  return (
    <ChatComposer
      id="home-composer"
      value={inputValue}
      onChange={setInputValue}
      onSubmit={handleSubmit}
      isLoading={isLoading}
      disabled={isLoading}
      placeholder={placeholder}
    />
  );
};

export default PromptComposer;
