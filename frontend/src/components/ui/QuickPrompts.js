import React from 'react';
import { cn, getRoleInfo } from '../../lib/utils';
import { 
  TrendingUp, Target, User, Brain, CheckCircle, Lightbulb,
  BarChart3, Users, Calendar, Shield, HelpCircle, BookOpen
} from 'lucide-react';
import { Button } from './Button';
import { Card, CardHeader, CardTitle, CardContent } from './Card';
import { Badge } from './Badge';

const getPromptIcon = (text) => {
  const icons = {
    'Q4 Financial Report': BarChart3,
    'Budget Analysis': TrendingUp,
    'Revenue Trends': TrendingUp,
    'Campaign Performance': Target,
    'Customer Insights': Users,
    'Brand Sentiment': Target,
    'Employee Metrics': Users,
    'Attendance Report': Calendar,
    'Performance Reviews': CheckCircle,
    'System Architecture': Brain,
    'Security Audit': Shield,
    'DevOps Metrics': BarChart3,
    'Executive Dashboard': BarChart3,
    'Strategic Goals': Target,
    'Growth Metrics': TrendingUp,
    'Company Events': Calendar,
    'HR Policies': BookOpen,
    'General Info': HelpCircle,
  };
  
  return icons[text] || Lightbulb;
};

export const QuickPrompts = ({
  userRole = 'employee',
  onPromptSelect,
  className,
  ...props
}) => {
  const roleInfo = getRoleInfo(userRole);

  // Quick prompts based on role
  const quickPrompts = {
    'finance': [
      { text: 'Q4 Financial Report', prompt: '📊 Show me the latest quarterly financial report with key metrics' },
      { text: 'Budget Analysis', prompt: '💰 Analyze our current budget allocation and spending trends' },
      { text: 'Revenue Trends', prompt: '📈 What are our revenue trends for the past 6 months?' },
      { text: 'Cost Optimization', prompt: '💡 Identify opportunities for cost optimization' },
    ],
    'marketing': [
      { text: 'Campaign Performance', prompt: '🎯 Show me our latest marketing campaign performance metrics' },
      { text: 'Customer Insights', prompt: '👥 What are the key customer insights from recent campaigns?' },
      { text: 'Brand Sentiment', prompt: '❤️ How is our brand sentiment tracking across channels?' },
      { text: 'Market Analysis', prompt: '📊 Provide current market analysis and competitive positioning' },
    ],
    'hr': [
      { text: 'Employee Metrics', prompt: '👥 Show me current employee satisfaction and retention metrics' },
      { text: 'Attendance Report', prompt: '📅 Generate attendance report for this month' },
      { text: 'Performance Reviews', prompt: '🏆 Summary of recent performance review cycles' },
      { text: 'Recruitment Status', prompt: '🔍 Current status of open positions and recruitment pipeline' },
    ],
    'engineering': [
      { text: 'System Architecture', prompt: '🏗️ Explain our current system architecture and tech stack' },
      { text: 'Security Audit', prompt: '🔐 Latest security audit results and recommendations' },
      { text: 'DevOps Metrics', prompt: '⚡ Display DevOps pipeline metrics and deployment stats' },
      { text: 'Performance Monitoring', prompt: '📈 System performance and monitoring insights' },
    ],
    'c_level': [
      { text: 'Executive Dashboard', prompt: '📊 Show me the complete executive dashboard with all KPIs' },
      { text: 'Strategic Goals', prompt: '🎯 Progress on strategic goals and initiatives' },
      { text: 'Growth Metrics', prompt: '📈 Key growth metrics and market position analysis' },
      { text: 'Risk Assessment', prompt: '⚠️ Current business risks and mitigation strategies' },
    ],
    'employee': [
      { text: 'Company Events', prompt: '📅 What are the upcoming company events and activities?' },
      { text: 'HR Policies', prompt: '❓ Explain the company HR policies and procedures' },
      { text: 'General Info', prompt: '☕ General company information and FAQs' },
      { text: 'Training Resources', prompt: '📚 Available training and development resources' },
    ]
  };

  const prompts = quickPrompts[userRole] || quickPrompts['employee'];

  const handlePromptClick = (prompt) => {
    if (onPromptSelect) {
      onPromptSelect(prompt.prompt);
    }
  };

  return (
    <Card 
      variant="outline" 
      padding="default"
      className={cn('max-w-4xl mx-auto', className)}
      {...props}
    >
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="w-5 h-5 text-brand" />
            Quick Prompts
          </CardTitle>
          <Badge variant="brand" size="sm">
            {roleInfo.name}
          </Badge>
        </div>
      </CardHeader>
      
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {prompts.map((prompt, index) => {
            const IconComponent = getPromptIcon(prompt.text);
            
            return (
              <Button
                key={index}
                variant="ghost"
                className="h-auto p-4 justify-start text-left hover:bg-muted/50 hover:border-primary/20 border border-transparent transition-all duration-200"
                onClick={() => handlePromptClick(prompt)}
              >
                <div className="flex flex-col items-start gap-2 w-full">
                  <div className="flex items-center gap-2">
                    <div className={cn(
                      'w-8 h-8 rounded-lg flex items-center justify-center',
                      `bg-gradient-to-br ${roleInfo.gradient} shadow-sm`
                    )}>
                      <IconComponent className="w-4 h-4 text-white" />
                    </div>
                    <span className="font-medium text-sm text-foreground">
                      {prompt.text}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground line-clamp-2">
                    {prompt.prompt}
                  </p>
                </div>
              </Button>
            );
          })}
        </div>

        {/* Additional Help */}
        <div className="mt-6 pt-4 border-t border-border">
          <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
            <HelpCircle className="w-4 h-4" />
            <span>Click any prompt to get started, or type your own question below</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
