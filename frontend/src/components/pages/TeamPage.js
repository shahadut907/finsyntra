import React from 'react';
import AppShell from '../layout/AppShell';
import GlassCard from '../ui/GlassCard';
import { Users } from 'lucide-react';

export const TeamPage = ({ user, onLogout, addNotification }) => {
  const handleOpenSearch = () => {
    addNotification('Advanced search coming soon!', 'info');
  };

  const handleOpenSettings = () => {
    addNotification('Settings coming soon!', 'info');
  };

  return (
    <AppShell 
      user={user} 
      onLogout={onLogout}
      onOpenSearch={handleOpenSearch}
      onOpenSettings={handleOpenSettings}
    >
      <div className="flex flex-col items-center justify-center min-h-screen text-center px-4">
        <GlassCard className="p-12 max-w-md">
          <Users size={48} className="text-finMint mx-auto mb-4" />
          <h1 className="text-2xl font-semibold text-white mb-4">
            Team Management
          </h1>
          <p className="text-mutedText leading-relaxed">
            User management and team collaboration features are coming soon. 
            Contact your administrator for user access and permissions.
          </p>
        </GlassCard>
      </div>
    </AppShell>
  );
};

export default TeamPage;
