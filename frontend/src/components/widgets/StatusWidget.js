import React, { useState, useEffect } from 'react';
import { Activity, Server, Database, Wifi, Zap } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui';

const StatusWidget = ({ apiCall, backendOnline }) => {
  const [status, setStatus] = useState({
    api: false,
    database: false,
    vectorStore: false,
    gpu: false
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 30000); // Check every 30 seconds
    return () => clearInterval(interval);
  }, [backendOnline]);

  const checkStatus = async () => {
    if (!backendOnline) return;
    
    setLoading(true);
    try {
      const response = await apiCall('/api/health');
      setStatus({
        api: response.components?.api || false,
        database: response.components?.database || false,
        vectorStore: response.components?.vector_store || false,
        gpu: response.gpu_optimized || false
      });
    } catch (error) {
      console.error('Failed to check status:', error);
      setStatus({
        api: false,
        database: false,
        vectorStore: false,
        gpu: false
      });
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (isOnline) => {
    return isOnline ? 'text-green-600' : 'text-red-600';
  };

  const statusItems = [
    { key: 'api', label: 'API', icon: Server, value: status.api },
    { key: 'database', label: 'Database', icon: Database, value: status.database },
    { key: 'vectorStore', label: 'Vector DB', icon: Wifi, value: status.vectorStore },
    { key: 'gpu', label: 'GPU', icon: Zap, value: status.gpu }
  ];

  return (
    <Card className="w-full">
      <CardHeader className="p-3">
        <div className="flex items-center gap-2">
          <Activity size={16} />
          <CardTitle className="text-sm">System Status</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        {loading ? (
          <div className="text-xs text-muted-foreground">Checking...</div>
        ) : (
          <div className="space-y-2">
            {statusItems.map((item) => (
              <div key={item.key} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <item.icon size={12} />
                  <span className="text-xs">{item.label}</span>
                </div>
                <div className={`w-2 h-2 rounded-full ${
                  item.value ? 'bg-green-500' : 'bg-red-500'
                }`} />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default StatusWidget;
