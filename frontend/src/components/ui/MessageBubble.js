import React from 'react';
import { cn, formatDate, copyToClipboard } from '../../lib/utils';
import { User, Bot, Copy, ThumbsUp, ThumbsDown, Star, MoreVertical } from 'lucide-react';
import { Button } from './Button';
import { Badge } from './Badge';
import { CompleteAvatar } from './Avatar';
import { Card } from './Card';

export const MessageBubble = ({
  message,
  isUser = false,
  isTyping = false,
  showTimestamp = true,
  showActions = true,
  onCopy,
  onFeedback,
  onStar,
  className,
  ...props
}) => {
  const [isHovered, setIsHovered] = React.useState(false);
  const [feedbackGiven, setFeedbackGiven] = React.useState(null);

  const handleCopy = async () => {
    const success = await copyToClipboard(message.text || message.content);
    if (success && onCopy) {
      onCopy('Message copied to clipboard');
    }
  };

  const handleFeedback = (type) => {
    setFeedbackGiven(type);
    if (onFeedback) {
      onFeedback(message.id, type);
    }
  };

  const formatContent = (content) => {
    if (!content) return '';

    // Escape first: content is model output / retrieved text and is injected
    // as HTML below, so only the markup added here may reach the DOM.
    const escaped = content
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');

    // Simple markdown-like formatting
    return escaped
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code class="px-1 py-0.5 bg-muted rounded text-sm font-mono">$1</code>');
  };

  return (
    <div
      className={cn(
        'group flex gap-3 max-w-4xl mx-auto px-4 py-4',
        isUser ? 'flex-row-reverse' : 'flex-row',
        className
      )}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      {...props}
    >
      {/* Avatar */}
      <div className="flex-shrink-0">
        <CompleteAvatar
          name={isUser ? 'You' : 'AI Assistant'}
          size="default"
          className={cn(
            isUser
              ? 'bg-primary text-primary-foreground'
              : 'bg-accent text-accent-foreground'
          )}
        >
          {isUser ? <User className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
        </CompleteAvatar>
      </div>

      {/* Message Content */}
      <div className={cn('flex-1 min-w-0', isUser && 'flex flex-col items-end')}>
        {/* Message Header */}
        <div className={cn(
          'flex items-center gap-2 mb-2',
          isUser ? 'flex-row-reverse' : 'flex-row'
        )}>
          <span className="font-medium text-sm text-foreground">
            {isUser ? 'You' : 'AI Assistant'}
          </span>
          {showTimestamp && message.timestamp && (
            <span className="text-xs text-muted-foreground">
              {formatDate(message.timestamp)}
            </span>
          )}
          {message.confidence && (
            <Badge
              variant={
                message.confidence >= 0.8 ? 'success' :
                  message.confidence >= 0.6 ? 'warning' : 'danger'
              }
              size="sm"
            >
              {Math.round(message.confidence * 100)}% confident
            </Badge>
          )}
        </div>

        {/* Message Bubble */}
        <Card
          variant={isUser ? 'default' : 'outline'}
          padding="default"
          className={cn(
            'relative max-w-3xl',
            isUser
              ? 'bg-primary text-primary-foreground ml-12'
              : 'bg-card text-card-foreground mr-12',
            isTyping && 'animate-pulse'
          )}
        >
          {/* Message Text */}
          <div
            className="prose prose-sm max-w-none dark:prose-invert"
            dangerouslySetInnerHTML={{
              __html: formatContent(message.text || message.content)
            }}
          />

          {/* Typing Indicator */}
          {isTyping && (
            <div className="flex items-center space-x-1 mt-2">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-current rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-2 h-2 bg-current rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-2 h-2 bg-current rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
              <span className="text-xs opacity-70 ml-2">AI is typing...</span>
            </div>
          )}

          {/* Sources */}
          {message.sources && message.sources.length > 0 && (() => {
            const uniqueSources = [...new Set(message.sources.map(s => s.name || s))];
            return (
              <div className="mt-3 pt-3 border-t border-border/50">
                <div className="text-xs text-muted-foreground mb-2">Sources:</div>
                <div className="flex flex-wrap gap-1">
                  {uniqueSources.map((source, index) => (
                    <Badge key={index} variant="muted" size="sm">
                      {source}
                    </Badge>
                  ))}
                </div>
              </div>
            );
          })()}
        </Card>

        {/* Message Actions */}
        {showActions && !isUser && (isHovered || feedbackGiven) && (
          <div className="flex items-center gap-1 mt-2 opacity-60 hover:opacity-100 transition-opacity">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={handleCopy}
              className="h-7 w-7"
            >
              <Copy className="w-3 h-3" />
            </Button>

            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => handleFeedback('positive')}
              className={cn(
                'h-7 w-7',
                feedbackGiven === 'positive' && 'text-success bg-success/10'
              )}
            >
              <ThumbsUp className="w-3 h-3" />
            </Button>

            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => handleFeedback('negative')}
              className={cn(
                'h-7 w-7',
                feedbackGiven === 'negative' && 'text-danger bg-danger/10'
              )}
            >
              <ThumbsDown className="w-3 h-3" />
            </Button>

            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => onStar?.(message.id)}
              className="h-7 w-7"
            >
              <Star className="w-3 h-3" />
            </Button>

            <Button
              variant="ghost"
              size="icon-sm"
              className="h-7 w-7"
            >
              <MoreVertical className="w-3 h-3" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};
