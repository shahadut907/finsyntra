import React from 'react';
import { motion } from 'framer-motion';
import GlassCard from './ui/GlassCard';

const FINSOLVE_PROMPTS = [
  {
    id: 'pdf-summary',
    text: 'Summarize this PDF for the board',
    icon: '📄'
  },
  {
    id: 'pl-variance',
    text: 'Explain last month\'s P&L variance',
    icon: '📊'
  },
  {
    id: 'draft-memo',
    text: 'Draft a memo from these notes',
    icon: '📝'
  },
  {
    id: 'policy-search',
    text: 'Find policy section on travel & expenses',
    icon: '🔍'
  }
];

export const QuickPrompts = ({ onPromptSelect, className = '' }) => {
  const handlePromptClick = (prompt) => {
    if (onPromptSelect) {
      onPromptSelect(prompt.text);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
      className={`space-y-3 ${className}`}
    >
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs font-medium text-mutedText uppercase tracking-wider">
          Quick Prompts
        </span>
        <div className="flex-1 h-px bg-white/10"></div>
      </div>
      
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {FINSOLVE_PROMPTS.map((prompt, index) => (
          <motion.div
            key={prompt.id}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.3, delay: index * 0.05 }}
            whileHover={{ scale: 1.02, y: -1 }}
            whileTap={{ scale: 0.98 }}
          >
            <GlassCard
              as="button"
              onClick={() => handlePromptClick(prompt)}
              className="p-3 text-left w-full cursor-pointer hover:bg-white/8 transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-finMint focus:ring-offset-2 focus:ring-offset-transparent"
              hover={false} // We handle hover in motion.div
            >
              <div className="flex items-center gap-3">
                <span className="text-lg flex-shrink-0">{prompt.icon}</span>
                <span className="text-white text-sm font-medium leading-tight">
                  {prompt.text}
                </span>
              </div>
            </GlassCard>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
};

export default QuickPrompts;
