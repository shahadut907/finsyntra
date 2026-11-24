// Error chip with retry functionality for failed chat messages
import React from 'react';
import { motion } from 'framer-motion';
import { RotateCcw, WifiOff, AlertCircle } from 'lucide-react';
import { cn } from '../../lib/utils';
import CorsErrorChip from './CorsErrorChip';

const ErrorChip = ({ 
  error, 
  onRetry, 
  className,
  messageId 
}) => {
  if (!error) return null;

  // Determine error type and messaging
  const getErrorInfo = (error) => {
    const message = error?.message || error || 'Unknown error';
    
    if (message.includes('Network offline') || !navigator.onLine) {
      return {
        type: 'offline',
        icon: WifiOff,
        title: 'You\'re offline',
        description: 'Check your connection and try again',
        canRetry: true
      };
    }
    
    if (message.includes('CORS') || 
        message.includes('blocked') ||
        message.includes('cross-origin') ||
        message.includes('Backend server CORS policy') ||
        message.includes('not configured for cross-origin')) {
      return {
        type: 'cors',
        icon: AlertCircle,
        title: 'Backend CORS configuration required',
        description: 'Server needs to allow requests from frontend',
        canRetry: true
      };
    }
    
    if (message.includes('timeout') || message.includes('Timeout')) {
      return {
        type: 'timeout',
        icon: AlertCircle,
        title: 'Request timed out',
        description: 'The server took too long to respond',
        canRetry: true
      };
    }
    
    if (message.includes('500') || message.includes('502') || message.includes('503')) {
      return {
        type: 'server',
        icon: AlertCircle,
        title: 'Server error',
        description: 'The server is experiencing issues',
        canRetry: true
      };
    }
    
    if (message.includes('Maximum retry')) {
      return {
        type: 'retry_failed',
        icon: AlertCircle,
        title: 'All retries failed',
        description: 'Unable to connect after multiple attempts',
        canRetry: true
      };
    }
    
    // Generic error
    return {
      type: 'generic',
      icon: AlertCircle,
      title: 'Message failed',
      description: message.length > 50 ? message.substring(0, 50) + '...' : message,
      canRetry: true
    };
  };

  const errorInfo = getErrorInfo(error);
  const Icon = errorInfo.icon;

  const handleRetry = () => {
    if (onRetry && errorInfo.canRetry) {
      onRetry(messageId);
    }
  };

  // Special handling for CORS errors - show detailed help
  if (errorInfo.type === 'cors') {
    return <CorsErrorChip onRetry={handleRetry} />;
  }

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, y: 10 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95, y: -10 }}
      transition={{ duration: 0.2 }}
      className={cn(
        "inline-flex items-center gap-2 px-3 py-2 mt-2",
        "bg-[color:var(--fs-danger-soft)] border border-[color:var(--fs-danger-border)] rounded-xl",
        "text-[color:var(--fs-danger)] text-sm",
        className
      )}
      role="alert"
      aria-live="polite"
    >
      <Icon size={14} className="text-[color:var(--fs-danger)] flex-shrink-0" />
      
      <div className="flex-1 min-w-0">
        <div className="font-medium text-[color:var(--fs-danger)]">{errorInfo.title}</div>
        {errorInfo.description && (
          <div className="text-[color:var(--fs-text-2)] text-xs mt-0.5 leading-tight">
            {errorInfo.description}
          </div>
        )}
      </div>

      {errorInfo.canRetry && onRetry && (
        <motion.button
          onClick={handleRetry}
          className={cn(
            "flex items-center gap-1 px-2 py-1",
            "bg-[color:var(--fs-fill)] hover:bg-[color:var(--fs-fill-hover)] border border-[color:var(--fs-danger-border)]",
            "rounded-md text-[color:var(--fs-danger)]",
            "text-xs font-medium transition-colors",
            "focus:outline-none focus:ring-2 focus:ring-red-500/50 focus:ring-offset-2 focus:ring-offset-transparent"
          )}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          aria-label={`Retry sending message: ${errorInfo.title}`}
        >
          <RotateCcw size={12} />
          Retry
        </motion.button>
      )}
    </motion.div>
  );
};

// Helper component for network status indicator  
export const NetworkStatus = ({ className }) => {
  const [isOnline, setIsOnline] = React.useState(navigator.onLine);

  React.useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  if (isOnline) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className={cn(
        "fixed top-4 left-1/2 transform -translate-x-1/2 z-50",
        "flex items-center gap-2 px-4 py-2",
        "bg-red-500/90 text-white rounded-lg shadow-lg",
        "text-sm font-medium",
        className
      )}
      role="alert"
      aria-live="assertive"
    >
      <WifiOff size={16} />
      You're offline
    </motion.div>
  );
};

export default ErrorChip;
