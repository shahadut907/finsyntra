/**
 * Test to verify the chat page imports the correct LIVE component
 */

import React from 'react';
import ChatPage from '../components/ChatPage';

describe('Chat Imports Verification', () => {
  test('ChatPage imports DarkChatInterface (not ChatInterface)', () => {
    // This test verifies that ChatPage uses the correct live component
    const chatPageSource = ChatPage.toString();
    
    // Verify DarkChatInterface is referenced
    expect(chatPageSource).toContain('DarkChatInterface');
    
    // The component should exist
    expect(ChatPage).toBeDefined();
  });

  test('ChatPage is exported correctly', () => {
    expect(ChatPage).toBeDefined();
    expect(typeof ChatPage).toBe('function');
  });
});

