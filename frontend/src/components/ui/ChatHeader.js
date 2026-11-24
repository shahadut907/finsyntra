import React from 'react';
import { cn, getRoleInfo } from '../../lib/utils';
import {
  Settings, Search, History, MoreVertical, Sun, Moon, LogOut,
  MessageSquare, Brain, Target, TrendingUp, User, CheckCircle
} from 'lucide-react';
import { Button } from './Button';
import { Badge } from './Badge';
import { CompleteAvatar } from './Avatar';
import { Card } from './Card';
import Logo from './Logo';

const roleIcons = {
  employee: User,
  engineering: Brain,
  finance: TrendingUp,
  marketing: Target,
  hr: User,
  c_level: CheckCircle,
};

export const ChatHeader = ({
  user,
  darkMode,
  onToggleTheme,
  onLogout,
  onSettings,
  onSearch,
  onConversationHistory,
  sessionId,
  className,
  ...props
}) => {
  const roleInfo = getRoleInfo(user?.role || 'employee');
  const RoleIcon = roleIcons[user?.role] || User;

  return (
    <Card
      variant="ghost"
      padding="default"
      className={cn(
        'sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60',
        className
      )}
      {...props}
    >
      <div className="flex items-center justify-between">
        {/* Left: Brand & User Info */}
        <div className="flex items-center space-x-4">
          {/* App Logo */}
          <div className="flex items-center space-x-3">
            <Logo size={40} showText={false} />
            <div className="hidden sm:block">
              <h1 className="text-lg font-semibold text-foreground">FinSyntra AI</h1>
              <p className="text-sm text-muted-foreground">{roleInfo.name} Assistant</p>
            </div>
          </div>

          {/* User Badge */}
          <div className="hidden md:flex items-center space-x-3">
            <div className="h-6 w-px bg-border" />
            <div className="flex items-center space-x-2">
              <CompleteAvatar
                name={user?.name}
                size="sm"
                className={cn('ring-2 ring-background', `ring-${roleInfo.color}-500/20`)}
              />
              <div className="hidden lg:block">
                <p className="text-sm font-medium text-foreground">
                  {user?.name || 'User'}
                </p>
                <Badge variant="muted" size="sm">
                  {roleInfo.name}
                </Badge>
              </div>
            </div>
          </div>
        </div>

        {/* Center: Session Info (optional) */}
        {sessionId && (
          <div className="hidden xl:flex items-center space-x-2">
            <MessageSquare className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">
              Session: {sessionId.slice(-8)}
            </span>
          </div>
        )}

        {/* Right: Actions */}
        <div className="flex items-center space-x-2">
          {/* Search */}
          <Button
            variant="ghost"
            size="icon"
            onClick={onSearch}
            className="hidden sm:inline-flex"
          >
            <Search className="w-4 h-4" />
          </Button>

          {/* Conversation History */}
          <Button
            variant="ghost"
            size="icon"
            onClick={onConversationHistory}
            className="hidden sm:inline-flex"
          >
            <History className="w-4 h-4" />
          </Button>

          {/* Settings */}
          <Button
            variant="ghost"
            size="icon"
            onClick={onSettings}
          >
            <Settings className="w-4 h-4" />
          </Button>

          {/* Theme Toggle */}
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleTheme}
            className="hidden sm:inline-flex"
          >
            {darkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </Button>

          {/* User Menu / Logout */}
          <div className="hidden sm:block h-6 w-px bg-border" />
          <Button
            variant="ghost"
            size="icon"
            onClick={onLogout}
            className="text-destructive hover:text-destructive hover:bg-destructive/10"
          >
            <LogOut className="w-4 h-4" />
          </Button>

          {/* Mobile More Menu */}
          <Button
            variant="ghost"
            size="icon"
            className="sm:hidden"
          >
            <MoreVertical className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </Card>
  );
};
