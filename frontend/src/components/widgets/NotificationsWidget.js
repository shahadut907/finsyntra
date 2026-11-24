import React, { useState, useEffect } from 'react';
import { Bell, BellOff, X } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui';

const NotificationsWidget = ({ apiCall, backendOnline }) => {
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    loadNotifications();
  }, [backendOnline]);

  const loadNotifications = async () => {
    if (!backendOnline) return;
    
    setLoading(true);
    try {
      // Mock notifications for now
      const mockNotifications = [
        {
          id: 1,
          title: 'System Update',
          message: 'New features available',
          type: 'info',
          timestamp: new Date().toISOString()
        },
        {
          id: 2,
          title: 'Security Alert',
          message: 'Password expires in 7 days',
          type: 'warning',
          timestamp: new Date().toISOString()
        }
      ];
      setNotifications(mockNotifications);
    } catch (error) {
      console.error('Failed to load notifications:', error);
    } finally {
      setLoading(false);
    }
  };

  const dismissNotification = (id) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  };

  if (!expanded) {
    return (
      <Card className="w-full">
        <CardHeader className="p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bell size={16} />
              <CardTitle className="text-sm">Notifications</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              {notifications.length > 0 && (
                <span className="bg-primary text-primary-foreground text-xs px-1.5 py-0.5 rounded-full">
                  {notifications.length}
                </span>
              )}
              <button
                onClick={() => setExpanded(true)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                View
              </button>
            </div>
          </div>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card className="w-full">
      <CardHeader className="p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bell size={16} />
            <CardTitle className="text-sm">Notifications</CardTitle>
          </div>
          <button
            onClick={() => setExpanded(false)}
            className="text-muted-foreground hover:text-foreground"
          >
            <X size={14} />
          </button>
        </div>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        {loading ? (
          <div className="text-xs text-muted-foreground">Loading...</div>
        ) : notifications.length === 0 ? (
          <div className="text-xs text-muted-foreground">No notifications</div>
        ) : (
          <div className="space-y-2">
            {notifications.slice(0, 3).map((notification) => (
              <div key={notification.id} className="bg-accent p-2 rounded text-xs">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="font-medium">{notification.title}</div>
                    <div className="text-muted-foreground">{notification.message}</div>
                  </div>
                  <button
                    onClick={() => dismissNotification(notification.id)}
                    className="text-muted-foreground hover:text-foreground ml-2"
                  >
                    <X size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default NotificationsWidget;
