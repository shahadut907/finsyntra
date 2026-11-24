import React from 'react';
import { cn, getRoleInfo } from '../../lib/utils';
import { Brain, MessageSquare, Sparkles, ArrowDown } from 'lucide-react';
import { Card, CardContent } from './Card';
import { Badge } from './Badge';

export const EmptyState = ({
  userRole = 'employee',
  userName = 'there',
  className,
  ...props
}) => {
  const roleInfo = getRoleInfo(userRole);

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  };

  const getRoleSpecificMessage = () => {
    const messages = {
      'finance': 'I can help you with financial reports, budget analysis, revenue trends, and cost optimization strategies.',
      'marketing': 'I can assist with campaign performance, customer insights, brand sentiment analysis, and market research.',
      'hr': 'I can provide employee metrics, attendance reports, performance reviews, and HR policy information.',
      'engineering': 'I can help with system architecture, security audits, DevOps metrics, and technical documentation.',
      'c_level': 'I can provide executive dashboards, strategic insights, growth metrics, and business intelligence.',
      'employee': 'I can help you with company information, HR policies, upcoming events, and general questions.',
    };
    
    return messages[userRole] || messages['employee'];
  };

  return (
    <div className={cn('flex flex-col items-center justify-center min-h-[60vh] px-4', className)} {...props}>
      {/* Main Welcome Card */}
      <Card variant="outline" className="max-w-2xl w-full text-center relative overflow-hidden">
        {/* Background Gradient */}
        <div className={cn(
          'absolute inset-0 opacity-5',
          `bg-gradient-to-br ${roleInfo.gradient}`
        )} />
        
        <CardContent className="relative py-12 px-8">
          {/* AI Avatar */}
          <div className="mb-6">
            <div className={cn(
              'w-20 h-20 mx-auto rounded-3xl flex items-center justify-center shadow-high relative',
              `bg-gradient-to-br ${roleInfo.gradient}`
            )}>
              <Brain className="w-10 h-10 text-white" />
              <div className="absolute -top-1 -right-1">
                <div className="w-6 h-6 bg-success rounded-full flex items-center justify-center">
                  <Sparkles className="w-3 h-3 text-white" />
                </div>
              </div>
            </div>
          </div>

          {/* Welcome Message */}
          <div className="space-y-4">
            <h1 className="text-2xl font-bold text-foreground">
              {getGreeting()}, {userName}! 👋
            </h1>
            
            <div className="flex items-center justify-center gap-2">
              <Badge variant="brand" className="flex items-center gap-1">
                <MessageSquare className="w-3 h-3" />
                FinSyntra AI Assistant
              </Badge>
              <Badge variant="muted">
                {roleInfo.name}
              </Badge>
            </div>

            <p className="text-muted-foreground text-lg leading-relaxed">
              {getRoleSpecificMessage()}
            </p>
          </div>

          {/* Features List */}
          <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div className="flex items-center gap-2 text-muted-foreground">
              <div className="w-2 h-2 bg-success rounded-full" />
              <span>Real-time responses</span>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground">
              <div className="w-2 h-2 bg-brand rounded-full" />
              <span>Role-based access</span>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground">
              <div className="w-2 h-2 bg-accent rounded-full" />
              <span>Document upload</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Quick Start Hint */}
      <div className="mt-8 flex items-center gap-2 text-sm text-muted-foreground animate-bounce">
        <ArrowDown className="w-4 h-4" />
        <span>Choose a quick prompt below or ask me anything</span>
        <ArrowDown className="w-4 h-4" />
      </div>

      {/* Privacy Note */}
      <div className="mt-4 text-xs text-muted-foreground max-w-md text-center">
        🔒 Your conversations are secure and role-based. I only have access to information relevant to your department.
      </div>
    </div>
  );
};
