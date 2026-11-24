// Health check system for API monitoring
import React from 'react';
import { HEALTH_URL } from '../config/chat';
import { debugLog, debugError } from '../config/env';

class HealthChecker {
  constructor() {
    this.status = 'unknown'; // 'healthy', 'unhealthy', 'unknown'
    this.lastCheck = null;
    this.listeners = new Set();
    this.checkInterval = null;
    this.isChecking = false;
  }

  // Subscribe to health status changes
  subscribe(callback) {
    this.listeners.add(callback);
    
    // Immediately notify with current status
    callback(this.status, this.lastCheck);
    
    // Return unsubscribe function
    return () => {
      this.listeners.delete(callback);
    };
  }

  // Notify all listeners of status change
  notify(newStatus) {
    if (newStatus !== this.status) {
      const oldStatus = this.status;
      this.status = newStatus;
      this.lastCheck = new Date();
      
      debugLog('Health status changed:', oldStatus, '->', newStatus);
      
      this.listeners.forEach(callback => {
        try {
          callback(this.status, this.lastCheck);
        } catch (error) {
          debugError('Health listener error:', error);
        }
      });
    }
  }

  // Perform health check
  async checkHealth() {
    if (this.isChecking) return this.status;
    
    this.isChecking = true;
    
    try {
      debugLog('Checking API health...');
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000); // 5s timeout for health checks
      
      const response = await fetch(HEALTH_URL, {
        method: 'GET',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
        },
        // Don't include credentials for health checks to avoid auth issues
      });
      
      clearTimeout(timeoutId);
      
      if (response.ok) {
        this.notify('healthy');
        debugLog('API health check: healthy');
      } else {
        this.notify('unhealthy');
        debugLog('API health check: unhealthy -', response.status);
      }
      
    } catch (error) {
      this.notify('unhealthy');
      debugError('API health check failed:', error.message);
    } finally {
      this.isChecking = false;
    }
    
    return this.status;
  }

  // Start periodic health checking
  startPeriodicChecking(intervalMs = 30000) { // Default 30 seconds
    this.stopPeriodicChecking();
    
    // Initial check
    this.checkHealth();
    
    // Set up interval
    this.checkInterval = setInterval(() => {
      this.checkHealth();
    }, intervalMs);
    
    debugLog('Started periodic health checking every', intervalMs, 'ms');
  }

  // Stop periodic health checking
  stopPeriodicChecking() {
    if (this.checkInterval) {
      clearInterval(this.checkInterval);
      this.checkInterval = null;
      debugLog('Stopped periodic health checking');
    }
  }

  // Get current health status
  getStatus() {
    return {
      status: this.status,
      lastCheck: this.lastCheck,
      isHealthy: this.status === 'healthy'
    };
  }

  // Manual refresh
  async refresh() {
    return await this.checkHealth();
  }
}

// Singleton instance
const healthChecker = new HealthChecker();

// React hook for health status
export const useHealth = () => {
  const [status, setStatus] = React.useState(healthChecker.getStatus());
  
  React.useEffect(() => {
    const unsubscribe = healthChecker.subscribe((newStatus, lastCheck) => {
      setStatus({
        status: newStatus,
        lastCheck,
        isHealthy: newStatus === 'healthy'
      });
    });
    
    return unsubscribe;
  }, []);
  
  const refresh = React.useCallback(() => {
    return healthChecker.refresh();
  }, []);
  
  return {
    ...status,
    refresh
  };
};

// Initialize health checking (call this once in app startup)
export const initializeHealthCheck = () => {
  healthChecker.startPeriodicChecking();
  
  // Cleanup on page unload
  const cleanup = () => {
    healthChecker.stopPeriodicChecking();
  };
  
  window.addEventListener('beforeunload', cleanup);
  
  return cleanup;
};

export default healthChecker;
