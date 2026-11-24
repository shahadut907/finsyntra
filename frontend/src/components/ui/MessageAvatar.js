import React from 'react';
import { motion } from 'framer-motion';

export const MessageAvatar = ({ 
  type = 'assistant', 
  userInitial = 'U', 
  className = '',
  size = 'default' 
}) => {
  const sizeClasses = {
    small: 'w-6 h-6 text-xs',
    default: 'w-8 h-8 text-sm',
    large: 'w-10 h-10 text-base'
  };

  if (type === 'assistant') {
    return (
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.2 }}
        className={`
          ${sizeClasses[size]} 
          flex items-center justify-center flex-shrink-0 rounded-lg
          bg-gradient-to-br from-finMint to-finTeal 
          shadow-lg shadow-finMint/25
          ${className}
        `}
        style={{
          filter: 'drop-shadow(0 0 8px rgba(56, 242, 181, 0.15))'
        }}
      >
        <span className="text-black font-bold">AI</span>
      </motion.div>
    );
  }

  // User avatar
  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.2 }}
      className={`
        ${sizeClasses[size]} 
        bg-finMint rounded-lg flex items-center justify-center flex-shrink-0
        ${className}
      `}
    >
      <span className="text-black font-bold">
        {userInitial}
      </span>
    </motion.div>
  );
};

export default MessageAvatar;
