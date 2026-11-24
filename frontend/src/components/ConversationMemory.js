import React, { useState, useEffect, useCallback } from 'react';
import {
  X, Brain, MessageSquare, User, Bot, Clock, Search, RefreshCw, Trash2,
  Eye, Download, Calendar, Database, Activity, CheckCircle, Target, Users,
  TrendingUp, BarChart3, MoreVertical
} from 'lucide-react';

const resolveResponse = async (resp) => {
  if (!resp) return null;
  if (typeof resp.json === 'function') {
    if (!resp.ok) return null;
    return await resp.json();
  }
  return resp;
};

// Helper functions for calculations
const extractTopicFromMessages = (messages) => {
  if (!messages || messages.length === 0) return null;

  // Simple topic extraction based on keywords
  const topics = {
    'finance': ['budget', 'revenue', 'profit', 'financial', 'money', 'cost'],
    'hr': ['employee', 'staff', 'hire', 'performance', 'attendance'],
    'marketing': ['campaign', 'customer', 'brand', 'marketing', 'sales'],
    'engineering': ['technical', 'system', 'code', 'development', 'api']
  };

  const text = messages.map(m => m.content || m.text || '').join(' ').toLowerCase();

  for (const [topic, keywords] of Object.entries(topics)) {
    if (keywords.some(keyword => text.includes(keyword))) {
      return topic;
    }
  }

  return 'general';
};

const calculateQualityScore = (session) => {
  let score = 0.5; // Base score

  if (session.message_count > 5) score += 0.2;
  if (session.current_topic && session.current_topic !== 'general') score += 0.2;
  if (session.conversation_mode === 'business') score += 0.1;

  return Math.min(1, score);
};

const calculateEngagementLevel = (session) => {
  const messageCount = session.message_count || 0;
  if (messageCount < 3) return 'low';
  if (messageCount < 10) return 'medium';
  return 'high';
};

const calculateTopicDistribution = (allSessions) => {
  const distribution = {};
  allSessions.forEach(session => {
    const topic = session.current_topic || 'unknown';
    distribution[topic] = (distribution[topic] || 0) + 1;
  });
  return distribution;
};

const calculateUserEngagement = (allSessions) => {
  const engagement = {};
  allSessions.forEach(session => {
    const level = session.engagement_level || 'unknown';
    engagement[level] = (engagement[level] || 0) + 1;
  });
  return engagement;
};

const calculatePeakHours = (allSessions) => {
  const hours = new Array(24).fill(0);
  allSessions.forEach(session => {
    const hour = new Date(session.created_at).getHours();
    hours[hour]++;
  });

  return hours.map((count, hour) => ({ hour, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
};

const calculateLanguageUsage = (allSessions) => {
  const languages = {};
  allSessions.forEach(session => {
    const lang = session.language || 'english';
    languages[lang] = (languages[lang] || 0) + 1;
  });
  return languages;
};

const ConversationMemory = ({ 
  isOpen, 
  onClose, 
  darkMode, 
  user, 
  apiCall, 
  addNotification,
  enableExportAll = false,
  // Render inside the app shell's content region instead of as a full-screen
  // modal over it (used by the /history page).
  embedded = false
}) => {
  const [activeTab, setActiveTab] = useState('sessions');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedSession, setSelectedSession] = useState(null);
  const [sessionDetails, setSessionDetails] = useState(null);
  const [allSessions, setAllSessions] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [filterType, setFilterType] = useState('all');
  const [sortBy, setSortBy] = useState('recent');
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [sessionToDelete, setSessionToDelete] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [sessionMenuOpenId, setSessionMenuOpenId] = useState(null);
  // Analytics state
  const [memoryStats, setMemoryStats] = useState({
    totalSessions: 0,
    activeSessions: 0,
    totalMessages: 0,
    avgMessagesPerSession: 0,
    topicDistribution: {},
    userEngagement: {},
    peakHours: [],
    languageUsage: {}
  });

  // Toggle auto-refresh function
  const toggleAutoRefresh = () => {
    setAutoRefresh(prev => !prev);
  };

  // Handle manual refresh function
  const handleManualRefresh = () => {
    loadAllSessions(true);
  };

  const tabs = [
    { id: 'sessions', label: 'Sessions', icon: MessageSquare, color: 'blue' },
    { id: 'memory', label: 'Memory Analysis', icon: Brain, color: 'purple' },
    { id: 'analytics', label: 'Analytics', icon: Activity, color: 'green' },
    { id: 'insights', label: 'AI Insights', icon: TrendingUp, color: 'orange' },
    { id: 'database', label: 'Database View', icon: Database, color: 'red' }
  ];

  // ENHANCED SESSION LOADER
  const userEmail = user?.email;
  const loadAllSessions = useCallback(async (showNotification = false) => {
    try {
      setIsLoading(showNotification);

      // Only /api/conversations exists server-side; probing further
      // endpoints just produces console noise (and /debug/* is dev-only).
      const endpoints = ['/api/conversations'];

      let sessionsData = [];
      for (const endpoint of endpoints) {
        try {
          const response = await apiCall(endpoint);
          const data = await resolveResponse(response);
          if (data && (data.sessions || data.length > 0)) {
            sessionsData = data.sessions || data;
            break;
          }
        } catch (error) {
          console.log(`Endpoint ${endpoint} failed:`, error);
          continue;
        }
      }

      // Real-time processing
      const processedSessions = sessionsData.map(session => ({
        id: session.id || session.session_id || `session_${Date.now()}_${Math.random()}`,
        session_name: session.session_name || session.name || `Session ${(session.id || session.session_id || '').slice(-8)}`,
        created_at: session.created_at || session.timestamp || new Date().toISOString(),
        updated_at: session.updated_at || session.last_activity || session.created_at || new Date().toISOString(),
        is_active: session.is_active !== undefined ? session.is_active : true,
        message_count: session.message_count || session.messages?.length || 0,
        user_id: session.user_id || userEmail || 'unknown',
        current_topic: session.current_topic || extractTopicFromMessages(session.messages),
        conversation_mode: session.conversation_mode || 'business',
        language: session.preferred_language || session.language || 'english',
        quality_score: calculateQualityScore(session),
        engagement_level: calculateEngagementLevel(session),
        last_updated: new Date().toISOString(),
        is_recent: new Date(session.updated_at || session.created_at) > new Date(Date.now() - 5 * 60 * 1000)
      }));

      setAllSessions(processedSessions);
      setLastUpdated(new Date());
      if (showNotification) addNotification('🧠 Real-time memory data updated', 'success');
    } catch (error) {
      console.error('Failed to load sessions:', error);
      if (showNotification) addNotification('❌ Failed to load memory data', 'error');
    } finally {
      if (showNotification) setIsLoading(false);
    }
  }, [apiCall, addNotification, userEmail]);

  // ENHANCED MEMORY STATS
  const calculateMemoryStats = useCallback(() => {
    const now = new Date();
    const recentCutoff = new Date(now.getTime() - 5 * 60 * 1000);

    const stats = {
      totalSessions: allSessions.length,
      activeSessions: allSessions.filter(s => s.is_active).length,
      recentSessions: allSessions.filter(s => new Date(s.updated_at) > recentCutoff).length,
      totalMessages: allSessions.reduce((sum, s) => sum + (s.message_count || 0), 0),
      avgMessagesPerSession: allSessions.length > 0 ? Math.round(allSessions.reduce((sum, s) => sum + (s.message_count || 0), 0) / allSessions.length) : 0,
      topicDistribution: calculateTopicDistribution(allSessions),
      userEngagement: calculateUserEngagement(allSessions),
      peakHours: calculatePeakHours(allSessions),
      languageUsage: calculateLanguageUsage(allSessions),
      lastUpdateTime: now.toISOString(),
      dataFreshness: 'live'
    };
    setMemoryStats(stats);
  }, [allSessions]);

  useEffect(() => {
    if (!isOpen) return;
    loadAllSessions();
    if (!autoRefresh) return;
    const interval = setInterval(loadAllSessions, 15000);
    return () => clearInterval(interval);
  }, [isOpen, autoRefresh, loadAllSessions]);

  useEffect(() => {
    calculateMemoryStats();
  }, [calculateMemoryStats]);

  if (!isOpen) return null;

  // ENHANCED SESSION DETAILS LOADER
  const loadSessionDetails = async (sessionId) => {
    try {
      setIsLoading(true);
      // Only /api/conversations/:id exists server-side.
      const endpoints = [`/api/conversations/${sessionId}`];
      let sessionData = null;
      for (const endpoint of endpoints) {
        try {
          const response = await apiCall(endpoint);
          const data = await resolveResponse(response);
          if (data) {
            sessionData = data;
            break;
          }
        } catch (error) {
          continue;
        }
      }
      if (sessionData) {
        setSessionDetails(sessionData);
        setSelectedSession(sessionId);
        addNotification('📄 Session details loaded', 'info');
      } else {
        // Never fabricate session content when the detail fetch fails.
        addNotification('Session details are unavailable for this conversation.', 'warning');
      }
    } catch (error) {
      console.error('Failed to load session details:', error);
      addNotification('❌ Failed to load session details', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  const clearSession = async (sessionId) => {
    setSessionToDelete(sessionId);
    setShowConfirmDialog(true);
  };

  const handleConfirmDelete = async () => {
    if (!sessionToDelete) return;

    try {
      setIsLoading(true);
      await apiCall(`/conversation/clear/${sessionToDelete}`, { method: 'POST' });
      addNotification('🗑️ Session cleared successfully', 'success');
      setShowConfirmDialog(false);
      setSessionToDelete(null);
      
      // Refresh sessions
      await loadAllSessions();
    } catch (error) {
      console.error('Failed to clear session:', error);
      addNotification('❌ Failed to clear session', 'error');
    } finally {
      setIsLoading(false);
      setShowConfirmDialog(false);
      setSessionToDelete(null);
    }
  };

  const exportSessionData = async (sessionId, format = 'json') => {
    try {
      const response = await apiCall(`/api/conversations/${sessionId}/export?format=${format}`, {
        method: 'GET'
      });

      if (!response || !response.ok) {
        const status = response?.status;
        if (status === 401 || status === 403) {
          addNotification('🔒 Session expired. Please sign in again.', 'warning');
        } else if (status === 408) {
          addNotification('⏱️ Server is taking too long. Try again.', 'warning');
        } else {
          addNotification('❌ Failed to export session', 'error');
        }
        return;
      }

      const dataBlob = await response.blob();
      const url = URL.createObjectURL(dataBlob);
      const link = document.createElement('a');
      link.href = url;
      const header = response.headers.get('Content-Disposition') || '';
      const match = header.match(/filename="([^"]+)"/);
      link.download = match?.[1] || `conversation_${sessionId}_${new Date().toISOString().split('T')[0]}.json`;
      link.click();
      URL.revokeObjectURL(url);
      addNotification('📄 Session data exported', 'success');
    } catch (error) {
      console.error('Failed to export session:', error);
      addNotification('❌ Failed to export session', 'error');
    }
  };

  const exportAllSessions = async () => {
    try {
      const allData = {
        export_date: new Date().toISOString(),
        user: user?.email,
        total_sessions: allSessions.length,
        sessions: allSessions,
        stats: memoryStats
      };
      
      const dataStr = JSON.stringify(allData, null, 2);
      const dataBlob = new Blob([dataStr], { type: 'application/json' });
      const url = URL.createObjectURL(dataBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `all_sessions_${new Date().toISOString().split('T')[0]}.json`;
      link.click();
      URL.revokeObjectURL(url);
      addNotification('📁 All sessions exported', 'success');
    } catch (error) {
      addNotification('❌ Failed to export all sessions', 'error');
    }
  };

  // Filter and sort sessions
  const filteredSessions = allSessions.filter(session => {
    const matchesSearch = session.session_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
                         session.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
                         session.current_topic?.toLowerCase().includes(searchTerm.toLowerCase());
    
    const matchesFilter = filterType === 'all' || 
                         (filterType === 'active' && session.is_active) ||
                         (filterType === 'recent' && new Date(session.created_at) > new Date(Date.now() - 24*60*60*1000)) ||
                         (filterType === 'high-engagement' && session.engagement_level === 'high');
    
    return matchesSearch && matchesFilter;
  }).sort((a, b) => {
    switch (sortBy) {
      case 'recent':
        return new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at);
      case 'messages':
        return (b.message_count || 0) - (a.message_count || 0);
      case 'quality':
        return (b.quality_score || 0) - (a.quality_score || 0);
      case 'name':
        return (a.session_name || '').localeCompare(b.session_name || '');
      default:
        return 0;
    }
  });

  // Responsive utility classes
  const cardClasses = `rounded-2xl border transition-all duration-300 ${
    darkMode 
      ? 'bg-gray-900/50 border-gray-800/60' 
      : 'bg-white/80 border-gray-200/60'
  } shadow-lg backdrop-blur-sm`;

  const StatCard = ({ title, value, icon: Icon, color = 'blue', description = null, trend = null }) => (
    <div className={`p-4 sm:p-6 ${cardClasses} hover:scale-105`}>
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-sm opacity-70 mb-1 truncate">{title}</p>
          <p className="text-2xl sm:text-3xl font-bold">{value}</p>
          {description && (
            <p className="text-xs opacity-60 mt-1">{description}</p>
          )}
          {trend && (
            <p className={`text-xs mt-2 flex items-center space-x-1 ${
              trend > 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              <TrendingUp className={`w-3 h-3 ${trend < 0 ? 'rotate-180' : ''}`} />
              <span>{Math.abs(trend)}%</span>
            </p>
          )}
        </div>
        <div className={`w-12 h-12 sm:w-16 sm:h-16 rounded-2xl bg-gradient-to-r ${
          color === 'blue' ? 'from-teal-500 to-teal-600' :
          color === 'green' ? 'from-green-500 to-green-600' :
          color === 'purple' ? 'from-emerald-500 to-emerald-600' :
          color === 'orange' ? 'from-orange-500 to-orange-600' :
          color === 'red' ? 'from-red-500 to-red-600' :
          'from-gray-500 to-gray-600'
        } flex items-center justify-center shadow-xl flex-shrink-0`}>
          <Icon className="w-6 h-6 sm:w-8 sm:h-8 text-white" />
        </div>
      </div>
    </div>
  );

  const renderSessions = () => (
    <div className="space-y-6">
      {/* Enhanced Controls */}
      <div className="flex flex-col lg:flex-row space-y-4 lg:space-y-0 lg:space-x-4">
        <div className="flex-1">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 opacity-40" />
            <input
              type="text"
              placeholder="Search sessions, topics, or content..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className={`w-full pl-10 pr-4 py-3 rounded-xl border ${
                darkMode 
                  ? 'bg-gray-900/90 border-gray-800/60 text-gray-100' 
                  : 'bg-gray-100/50 border-gray-200/40 text-gray-900'
              }`}
            />
          </div>
        </div>
        
        <div className="flex space-x-4">
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className={`px-4 py-3 rounded-xl border ${
              darkMode 
                ? 'bg-gray-900/90 border-gray-800/60 text-gray-100' 
                : 'bg-gray-100/50 border-gray-200/40 text-gray-900'
            }`}
          >
            <option value="all">All Sessions</option>
            <option value="active">Active Only</option>
            <option value="recent">Recent (24h)</option>
            <option value="high-engagement">High Engagement</option>
          </select>
          
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className={`px-4 py-3 rounded-xl border ${
              darkMode 
                ? 'bg-gray-900/90 border-gray-800/60 text-gray-100' 
                : 'bg-gray-100/50 border-gray-200/40 text-gray-900'
            }`}
          >
            <option value="recent">Most Recent</option>
            <option value="messages">Most Messages</option>
            <option value="quality">Highest Quality</option>
            <option value="name">Name A-Z</option>
          </select>

          {enableExportAll && (
            <button
              onClick={exportAllSessions}
              className="px-4 py-3 bg-green-500/20 hover:bg-green-500/30 text-green-400 rounded-xl transition-colors"
              title="Export All Sessions"
            >
              <Download className="w-5 h-5" />
            </button>
          )}
          
          <button
            onClick={loadAllSessions}
            disabled={isLoading}
            className="px-4 py-3 bg-teal-500/20 hover:bg-teal-500/30 text-teal-400 rounded-xl transition-colors disabled:opacity-50"
            title="Refresh Sessions"
          >
            <RefreshCw className={`w-5 h-5 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* FIXED: Enhanced Auto-refresh controls with real-time indicators */}
      <div className={`p-4 sm:p-6 ${cardClasses}`}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Real-time Controls</h3>
          <div className="flex items-center space-x-4">
            {/* Real-time Status Indicator */}
            <div className="flex items-center space-x-2">
              <div className={`w-2 h-2 rounded-full ${autoRefresh ? 'bg-green-500 animate-pulse' : 'bg-gray-500'}`}></div>
              <span className="text-sm">{autoRefresh ? 'Live Updates' : 'Paused'}</span>
            </div>

            {/* Last Updated Timestamp */}
            <span className="text-xs opacity-60">Updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : '--'}</span>

            {/* Auto-refresh Toggle */}
            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={toggleAutoRefresh}
                className="rounded border-gray-300"
              />
              <span className="text-sm">Auto-refresh (5s)</span>
            </label>

            {/* Manual Refresh Button */}
            <button
              onClick={handleManualRefresh}
              disabled={isLoading}
              className={`px-4 py-3 bg-teal-500/20 hover:bg-teal-500/30 text-teal-400 rounded-xl transition-colors ${isLoading ? 'opacity-50' : ''}`}
              title="Manual Refresh"
            >
              <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
              Refresh Now
            </button>
          </div>
        </div>

        {/* Real-time Data Quality Indicators */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="text-center p-3 rounded-lg bg-teal-500/10">
            <Activity className="w-6 h-6 mx-auto mb-2 text-teal-400" />
            <p className="text-sm font-bold">{memoryStats.totalSessions}</p>
            <p className="text-xs opacity-60">Total Sessions</p>
          </div>
          <div className="text-center p-3 rounded-lg bg-green-500/10">
            <CheckCircle className="w-6 h-6 mx-auto mb-2 text-green-400" />
            <p className="text-sm font-bold">{memoryStats.activeSessions}</p>
            <p className="text-xs opacity-60">Active Now</p>
          </div>
          <div className="text-center p-3 rounded-lg bg-emerald-500/10">
            <Clock className="w-6 h-6 mx-auto mb-2 text-emerald-400" />
            <p className="text-sm font-bold">{memoryStats.recentSessions || 0}</p>
            <p className="text-xs opacity-60">Recent (5min)</p>
          </div>
          <div className="text-center p-3 rounded-lg bg-orange-500/10">
            <Database className="w-6 h-6 mx-auto mb-2 text-orange-400" />
            <p className="text-sm font-bold">{autoRefresh ? 'LIVE' : 'STATIC'}</p>
            <p className="text-xs opacity-60">Data Mode</p>
          </div>
        </div>

        {/* Refresh Rate Controls */}
        <div className="mt-4 p-3 bg-gray-500/10 rounded-lg">
          <h4 className="text-sm font-medium mb-2">Real-time Settings</h4>
          <div className="flex items-center justify-between text-sm">
            <span>Session Refresh Rate:</span>
            <span className="text-teal-400">5 seconds</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span>Analytics Refresh Rate:</span>
            <span className="text-emerald-400">15 seconds</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span>Data Quality:</span>
            <span className={`${memoryStats.totalSessions > 0 ? 'text-green-400' : 'text-yellow-400'}`}>{memoryStats.totalSessions > 0 ? 'High' : 'Limited'}</span>
          </div>
        </div>
      </div>

      {/* Sessions List */}
      <div className="space-y-4">
        {filteredSessions.length === 0 ? (
          <div className={`p-8 rounded-xl border text-center ${cardClasses}`}>
            <Brain className="w-12 h-12 mx-auto mb-4 opacity-40" />
            <p className="text-lg font-medium mb-2">No sessions found</p>
            <p className="text-sm opacity-60">
              {searchTerm ? 'Try adjusting your search terms' : 'Start a conversation to see memory data'}
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            {filteredSessions.map((session) => (
              <div 
                key={session.id} 
                className={`p-4 sm:p-6 rounded-xl border transition-all duration-300 hover:scale-[1.02] ${
                  darkMode 
                    ? 'bg-gray-900/50 border-gray-800/60 hover:bg-gray-900/70' 
                    : 'bg-white/80 border-gray-200/60 hover:bg-white/90'
                } shadow-lg backdrop-blur-sm`}
              >
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between space-y-4 sm:space-y-0">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center space-x-3 mb-3">
                      <MessageSquare className="w-5 h-5 text-emerald-500 flex-shrink-0" />
                      <h3 className="font-semibold truncate">{session.session_name || `Session ${session.id.slice(-8)}`}</h3>
                      {session.is_active && (
                        <span className="px-2 py-1 bg-green-500/20 text-green-400 text-xs rounded-full flex-shrink-0">ACTIVE</span>
                      )}
                      <span className={`px-2 py-1 text-xs rounded-full flex-shrink-0 ${
                        session.engagement_level === 'high' ? 'bg-green-500/20 text-green-400' :
                        session.engagement_level === 'medium' ? 'bg-yellow-500/20 text-yellow-400' :
                        'bg-gray-500/20 text-gray-400'
                      }`}>
                        {session.engagement_level?.toUpperCase() || 'LOW'}
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm opacity-80">
                      <div className="flex items-center space-x-2">
                        <Clock className="w-4 h-4 flex-shrink-0" />
                        <span className="truncate">{new Date(session.created_at).toLocaleDateString()}</span>
                      </div>
                      <div className="flex items-center space-x-2">
                        <MessageSquare className="w-4 h-4 flex-shrink-0" />
                        <span>{session.message_count || 0} messages</span>
                      </div>
                      <div className="flex items-center space-x-2">
                        <Target className="w-4 h-4 flex-shrink-0" />
                        <span className="truncate">{session.current_topic || 'General'}</span>
                      </div>
                      <div className="flex items-center space-x-2">
                        <BarChart3 className="w-4 h-4 flex-shrink-0" />
                        <span className="text-teal-400">
                          {Math.round((session.quality_score || 0.5) * 100)}% Quality
                        </span>
                      </div>
                    </div>
                    
                    {session.conversation_mode && (
                      <div className="mt-2">
                        <span className={`inline-flex items-center px-2 py-1 text-xs rounded-full ${
                          session.conversation_mode === 'business' ? 'bg-teal-500/20 text-teal-400' :
                          session.conversation_mode === 'casual' ? 'bg-emerald-500/20 text-emerald-400' :
                          'bg-gray-500/20 text-gray-400'
                        }`}>
                          {session.conversation_mode} • {session.language || 'english'}
                        </span>
                      </div>
                    )}
                  </div>
                  
                  <div className="flex flex-wrap items-center gap-2 sm:ml-4">
                    <button 
                      onClick={() => loadSessionDetails(session.id)}
                      className="p-2 rounded-lg bg-teal-500/20 hover:bg-teal-500/30 text-teal-400 transition-colors"
                      title="View Details"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                    
                    <div className="relative">
                      <button 
                        onClick={() => setSessionMenuOpenId(prev => (prev === session.id ? null : session.id))}
                        className="p-2 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 transition-colors"
                        title="More actions"
                        aria-haspopup="menu"
                        aria-expanded={sessionMenuOpenId === session.id}
                      >
                        <MoreVertical className="w-4 h-4" />
                      </button>
                      {sessionMenuOpenId === session.id && (
                        <div
                          className={`absolute right-0 mt-2 w-44 rounded-lg border shadow-lg z-10 ${
                            darkMode 
                              ? 'bg-gray-950/95 border-gray-800/60 text-gray-100' 
                              : 'bg-white border-gray-200 text-gray-900'
                          }`}
                          role="menu"
                        >
                          <button
                            onClick={() => {
                              exportSessionData(session.id, 'json');
                              setSessionMenuOpenId(null);
                            }}
                            className="w-full text-left px-3 py-2 text-sm hover:bg-emerald-500/10"
                            role="menuitem"
                          >
                            Export JSON
                          </button>
                          <button
                            onClick={() => {
                              exportSessionData(session.id, 'md');
                              setSessionMenuOpenId(null);
                            }}
                            className="w-full text-left px-3 py-2 text-sm hover:bg-emerald-500/10"
                            role="menuitem"
                          >
                            Export Markdown
                          </button>
                        </div>
                      )}
                    </div>
                    
                    <button 
                      onClick={() => clearSession(session.id)}
                      className="p-2 rounded-lg bg-red-500/20 hover:bg-red-500/30 text-red-400 transition-colors"
                      title="Clear Session"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Session Details Modal */}
      {selectedSession && sessionDetails && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className={`w-full max-w-6xl max-h-[90vh] overflow-hidden rounded-2xl shadow-2xl border ${
            darkMode 
              ? 'bg-gray-950/98 text-gray-100 border-gray-800/60' 
              : 'bg-white/95 text-gray-900 border-gray-200/60'
          }`}>
            <div className="flex items-center justify-between p-6 border-b border-gray-800/60">
              <h3 className="text-xl font-semibold">Session Details</h3>
              <button 
                onClick={() => {
                  setSelectedSession(null);
                  setSessionDetails(null);
                }}
                className="p-2 rounded-full hover:bg-gray-500/20"
              >
                <X className="w-5 h-5 opacity-60" />
              </button>
            </div>

            <div className="p-6 overflow-y-auto max-h-[70vh]">
              {/* Session Info */}
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
                <StatCard 
                  title="Messages" 
                  value={sessionDetails.message_count || sessionDetails.messages?.length || 0} 
                  icon={MessageSquare} 
                  color="blue"
                />
                <StatCard 
                  title="Created" 
                  value={sessionDetails.created_at ? new Date(sessionDetails.created_at).toLocaleDateString() : 'N/A'} 
                  icon={Clock} 
                  color="purple"
                />
                <StatCard 
                  title="Last Activity" 
                  value={sessionDetails.updated_at ? new Date(sessionDetails.updated_at).toLocaleDateString() : 'N/A'} 
                  icon={TrendingUp} 
                  color="green"
                />
              </div>

              {/* Messages */}
              <div className={cardClasses}>
                <div className="p-4">
                  <h4 className="font-semibold mb-4">Conversation Messages</h4>
                  <div className="space-y-3 max-h-96 overflow-y-auto">
                    {sessionDetails.messages?.map((message, index) => (
                      <div 
                        key={index} 
                        className={`p-3 rounded-lg ${
                          message.message_type === 'user' 
                            ? 'bg-teal-500/20 ml-4 sm:ml-8' 
                            : 'bg-gray-500/20 mr-4 sm:mr-8'
                        }`}
                      >
                        <div className="flex items-center space-x-2 mb-2">
                          {message.message_type === 'user' ? (
                            <User className="w-4 h-4 text-teal-400" />
                          ) : (
                            <Bot className="w-4 h-4 text-green-400" />
                          )}
                          <span className="text-sm font-medium capitalize">
                            {message.message_type}
                          </span>
                          <span className="text-xs opacity-60">
                            {new Date(message.created_at).toLocaleTimeString()}
                          </span>
                          {message.metadata?.confidence && (
                            <span className="text-xs bg-green-500/20 text-green-400 px-2 py-1 rounded">
                              {Math.round(message.metadata.confidence * 100)}% confidence
                            </span>
                          )}
                        </div>
                        <p className="text-sm break-words">{message.content}</p>
                        {message.metadata?.sources && message.metadata.sources.length > 0 && (
                          <div className="mt-2 pt-2 border-t border-gray-500/20">
                            <p className="text-xs opacity-60 mb-1">Sources:</p>
                            <div className="flex flex-wrap gap-1">
                              {message.metadata.sources.map((source, idx) => (
                                <span key={idx} className="text-xs bg-teal-500/20 text-teal-400 px-2 py-1 rounded">
                                  {source}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )) || (
                      <p className="text-center text-gray-500 py-8">No messages in this session</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const renderMemoryAnalysis = () => {
    const dayAgoMs = Date.now() - 24 * 60 * 60 * 1000;
    const recent24hCount = allSessions.filter(s => new Date(s.updated_at).getTime() > dayAgoMs).length;
    return (
    <div className="space-y-8">
      {/* Memory Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
        <StatCard 
          title="Total Sessions" 
          value={memoryStats.totalSessions} 
          icon={MessageSquare} 
          color="blue"
          description="All conversations"
        />
        <StatCard 
          title="Active Sessions" 
          value={memoryStats.activeSessions} 
          icon={Activity} 
          color="green"
          description="Currently active"
        />
        <StatCard 
          title="Total Messages" 
          value={memoryStats.totalMessages} 
          icon={Brain} 
          color="purple"
          description="Across all sessions"
        />
        <StatCard 
          title="Avg Messages/Session" 
          value={memoryStats.avgMessagesPerSession} 
          icon={Target} 
          color="orange"
          description="Per conversation"
        />
      </div>

      {/* Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Activity (real: updated_at within 24h) */}
        <div className={`p-6 ${cardClasses}`}>
          <h3 className="text-lg font-semibold mb-4">Recent Activity</h3>
          <div className="text-center p-6 rounded-xl bg-teal-500/20 text-teal-400">
            <CheckCircle className="w-12 h-12 mx-auto mb-3" />
            <h4 className="text-xl font-bold mb-2">{recent24hCount}</h4>
            <p className="text-sm opacity-80">sessions updated in the last 24 hours</p>
          </div>
        </div>

        {/* Topic Distribution */}
        <div className={`p-6 ${cardClasses}`}>
          <h3 className="text-lg font-semibold mb-4">Topic Distribution</h3>
          <div className="space-y-3">
            {Object.entries(memoryStats.topicDistribution).map(([topic, count]) => {
              const percentage = memoryStats.totalSessions > 0 ? 
                Math.round((count / memoryStats.totalSessions) * 100) : 0;
              return (
                <div key={topic} className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="capitalize">{topic}</span>
                    <span>{count} sessions ({percentage}%)</span>
                  </div>
                  <div className="w-full bg-gray-700 rounded-full h-2">
                    <div 
                      className="bg-teal-500 h-2 rounded-full transition-all duration-300" 
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Engagement & Language Analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* User Engagement */}
        <div className={`p-6 ${cardClasses}`}>
          <h3 className="text-lg font-semibold mb-4">User Engagement Levels</h3>
          <div className="space-y-4">
            {Object.entries(memoryStats.userEngagement).map(([level, count]) => (
              <div key={level} className="flex justify-between items-center">
                <span className="text-sm capitalize">{level} Engagement</span>
                <div className="flex items-center space-x-2">
                  <span className="text-sm font-medium">{count}</span>
                  <div className={`w-3 h-3 rounded-full ${
                    level === 'high' ? 'bg-green-500' :
                    level === 'medium' ? 'bg-yellow-500' :
                    'bg-red-500'
                  }`} />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Peak Hours */}
        <div className={`p-6 ${cardClasses}`}>
          <h3 className="text-lg font-semibold mb-4">Peak Activity Hours</h3>
          <div className="space-y-3">
            {memoryStats.peakHours.slice(0, 5).map((hour, index) => (
              <div key={hour.hour} className="flex justify-between items-center">
                <span className="text-sm">
                  {hour.hour}:00 - {hour.hour + 1}:00
                </span>
                <div className="flex items-center space-x-2">
                  <div className="w-16 bg-gray-700 rounded-full h-2">
                    <div 
                      className="bg-emerald-500 h-2 rounded-full" 
                      style={{ width: `${(hour.count / Math.max(...memoryStats.peakHours.map(h => h.count))) * 100}%` }}
                    />
                  </div>
                  <span className="text-sm font-medium w-8">{hour.count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className={`p-6 ${cardClasses}`}>
        <h3 className="text-lg font-semibold mb-4">Memory Actions</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <button 
            onClick={loadAllSessions}
            disabled={isLoading}
            className="flex items-center space-x-3 p-4 rounded-xl bg-teal-500/20 hover:bg-teal-500/30 text-teal-400 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-5 h-5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh Memory</span>
          </button>
          {enableExportAll && (
            <button 
              onClick={exportAllSessions}
              className="flex items-center space-x-3 p-4 rounded-xl bg-green-500/20 hover:bg-green-500/30 text-green-400 transition-colors"
            >
              <Download className="w-5 h-5" />
              <span>Export All Data</span>
            </button>
          )}
          <button 
            onClick={() => calculateMemoryStats()}
            className="flex items-center space-x-3 p-4 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 transition-colors"
          >
            <BarChart3 className="w-5 h-5" />
            <span>Recalculate Stats</span>
          </button>
        </div>
      </div>
    </div>
    );
  };

  const renderAnalytics = () => {
    // Every figure here is computed from the real session list
    // (/api/conversations) — no server-side analytics endpoint exists, so
    // nothing is invented or defaulted to a placeholder value.
    const totalSessions = allSessions.length;
    const totalMessages = allSessions.reduce((sum, s) => sum + (s.message_count || 0), 0);

    const hourCounts = new Array(24).fill(0);
    allSessions.forEach(s => {
      const h = new Date(s.created_at).getHours();
      if (!Number.isNaN(h)) hourCounts[h]++;
    });
    const maxHourly = Math.max(1, ...hourCounts);
    const peakHour = hourCounts.indexOf(Math.max(...hourCounts));

    const dayMs = 24 * 60 * 60 * 1000;
    const trendDays = 14;
    const startOfToday = new Date();
    startOfToday.setHours(0, 0, 0, 0);
    const dailyCounts = Array.from({ length: trendDays }, (_, i) => {
      const dayStart = startOfToday.getTime() - (trendDays - 1 - i) * dayMs;
      const dayEnd = dayStart + dayMs;
      return {
        label: new Date(dayStart).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
        count: allSessions.filter(s => {
          const t = new Date(s.created_at).getTime();
          return t >= dayStart && t < dayEnd;
        }).length
      };
    });
    const maxDaily = Math.max(1, ...dailyCounts.map(d => d.count));

    const sessionsByUser = {};
    allSessions.forEach(s => {
      const owner = s.user_id || 'unknown';
      sessionsByUser[owner] = (sessionsByUser[owner] || 0) + 1;
    });
    const topUsers = Object.entries(sessionsByUser).sort((a, b) => b[1] - a[1]).slice(0, 5);
    const maxUserSessions = Math.max(1, ...topUsers.map(([, c]) => c));

    return (
      <div className="space-y-8">
        {/* Analytics Overview */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
          <StatCard
            title="Total Sessions"
            value={totalSessions}
            icon={Calendar}
            color="blue"
            description="All conversations"
          />
          <StatCard
            title="Total Messages"
            value={totalMessages}
            icon={MessageSquare}
            color="green"
            description="Across all sessions"
          />
          <StatCard
            title="Avg Messages/Session"
            value={totalSessions > 0 ? Math.round(totalMessages / totalSessions) : 0}
            icon={Target}
            color="purple"
            description="Per conversation"
          />
          <StatCard
            title="Peak Start Hour"
            value={totalSessions > 0 ? peakHour + ':00' : '—'}
            icon={Clock}
            color="orange"
            description="Most common session start hour"
          />
        </div>

        {/* Sessions per Day */}
        <div className={`p-6 ${cardClasses}`}>
          <h3 className="text-lg font-semibold mb-4">Sessions per Day (last 14 days)</h3>
          <div className="h-64 flex items-end justify-between space-x-1">
            {dailyCounts.map((day, index) => (
              <div key={index} className="flex flex-col items-center space-y-2 flex-1 min-w-0">
                <div
                  className="bg-teal-500 rounded-t w-full transition-all duration-300 hover:bg-teal-400"
                  style={{ height: (day.count / maxDaily) * 100 + '%', minHeight: '4px' }}
                  title={day.label + ': ' + day.count + ' session' + (day.count !== 1 ? 's' : '')}
                />
                <span className="text-xs opacity-60 whitespace-nowrap overflow-hidden text-ellipsis max-w-full">
                  {day.label}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Hourly Activity */}
        <div className={`p-6 ${cardClasses}`}>
          <h3 className="text-lg font-semibold mb-4">Session Starts by Hour</h3>
          <div className="h-64 flex items-end justify-between space-x-1">
            {hourCounts.map((count, hour) => (
              <div key={hour} className="flex flex-col items-center space-y-2 flex-1">
                <div
                  className="bg-green-500 rounded-t w-full transition-all duration-300 hover:bg-green-400"
                  style={{ height: (count / maxHourly) * 100 + '%', minHeight: '4px' }}
                  title={hour + ':00 — ' + count + ' session' + (count !== 1 ? 's' : '')}
                />
                <span className="text-xs opacity-60">
                  {hour % 3 === 0 ? hour : ''}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Most Active Users */}
        <div className={`p-6 ${cardClasses}`}>
          <h3 className="text-lg font-semibold mb-4">Most Active Users</h3>
          {topUsers.length === 0 ? (
            <p className="text-center opacity-60 py-6">No sessions yet</p>
          ) : (
            <div className="space-y-4">
              {topUsers.map(([owner, count]) => (
                <div key={owner} className="space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="font-medium truncate">{owner}</span>
                    <span className="text-sm opacity-60 flex-shrink-0 ml-3">{count} session{count !== 1 ? 's' : ''}</span>
                  </div>
                  <div className="w-full bg-gray-700 rounded-full h-2">
                    <div
                      className="h-2 rounded-full bg-teal-500 transition-all duration-300"
                      style={{ width: (count / maxUserSessions) * 100 + '%' }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderInsights = () => {
    const totalSessions = allSessions.length;
    const totalMessages = allSessions.reduce((sum, s) => sum + (s.message_count || 0), 0);
    const activeUsers = new Set(allSessions.map(s => s.user_id).filter(Boolean)).size;

    return (
      <div className="space-y-8">
        <div className="text-center py-8">
          <Brain className="w-16 h-16 mx-auto mb-4 opacity-40" />
          <h3 className="text-xl font-semibold mb-2">Usage Summary</h3>
          <p className="text-gray-500 mb-6">Computed from your conversation history. No estimated or projected figures are shown.</p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-4xl mx-auto">
            <div className={`p-6 ${cardClasses}`}>
              <MessageSquare className="w-12 h-12 mx-auto mb-4 text-teal-400" />
              <h4 className="text-2xl font-bold mb-2">{totalSessions}</h4>
              <p className="text-sm opacity-70">Conversations stored</p>
            </div>
            <div className={`p-6 ${cardClasses}`}>
              <Activity className="w-12 h-12 mx-auto mb-4 text-green-400" />
              <h4 className="text-2xl font-bold mb-2">{totalMessages}</h4>
              <p className="text-sm opacity-70">Messages exchanged</p>
            </div>
            <div className={`p-6 ${cardClasses}`}>
              <Users className="w-12 h-12 mx-auto mb-4 text-emerald-400" />
              <h4 className="text-2xl font-bold mb-2">{activeUsers}</h4>
              <p className="text-sm opacity-70">Users with conversations</p>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderDatabase = () => (
    <div className="space-y-8">
      <div className="text-center py-8">
        <Database className="w-16 h-16 mx-auto mb-4 opacity-40" />
        <h3 className="text-xl font-semibold mb-2">Database Management</h3>
        <p className="text-gray-500 mb-6">Direct database access and management tools</p>
        
        <div className={`p-6 ${cardClasses} text-left max-w-4xl mx-auto`}>
          <h4 className="font-medium mb-4">Database Connection Status:</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-6">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm">Connection Status</span>
                <span className="flex items-center space-x-2 text-green-400">
                  <CheckCircle className="w-4 h-4" />
                  <span>Connected</span>
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">Database Type</span>
                <span className="text-sm font-medium">SQLite</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">Total Sessions</span>
                <span className="text-sm font-medium">{allSessions.length}</span>
              </div>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm">Total Messages</span>
                <span className="text-sm font-medium">{memoryStats.totalMessages}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">Data Location</span>
                <span className="text-sm font-medium">Local server storage</span>
              </div>
            </div>
          </div>
          
          <div className="border-t border-gray-500/20 pt-4">
            <h5 className="font-medium mb-3">Stored Records:</h5>
            <div className="space-y-2 text-sm opacity-70 font-mono">
              <div>📊 chat_sessions ({allSessions.length} records)</div>
              <div>💬 chat_messages ({memoryStats.totalMessages} records)</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  const renderContent = () => {
    switch (activeTab) {
      case 'sessions': return renderSessions();
      case 'memory': return renderMemoryAnalysis();
      case 'analytics': return renderAnalytics();
      case 'insights': return renderInsights();
      case 'database': return renderDatabase();
      default: return renderSessions();
    }
  };

  return (
    <div className={embedded ? 'flex flex-1 min-h-0 min-w-0 fs-legacy-colors' : 'fixed inset-0 z-50 flex bg-black/50 backdrop-blur-sm fs-legacy-colors'}>
      <div className={`w-full h-full min-w-0 flex flex-col ${embedded ? '' : 'rounded-lg sm:rounded-3xl sm:m-4 shadow-2xl border transition-all duration-300'} ${
        embedded
          ? 'text-[color:var(--fs-text)]'
          : darkMode 
            ? 'bg-gray-950/98 text-gray-100 border-gray-800/60' 
            : 'bg-white/95 text-gray-900 border-gray-200/60'
      } overflow-hidden`}>
        
        {/* Header (the app shell header already titles the embedded page) */}
        {!embedded && (
        <div className="flex items-center justify-between p-4 sm:p-6 border-b border-gray-800/60 flex-shrink-0">
          <div className="flex items-center space-x-3">
            <Brain className="w-6 h-6 sm:w-8 sm:h-8 text-emerald-500" />
            <div>
              <h1 className="text-xl sm:text-2xl font-bold">Conversation Memory</h1>
              <p className="text-sm opacity-60 hidden sm:block">Advanced memory analysis and session management</p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-2 rounded-full hover:bg-gray-500/20 transition-colors duration-200"
          >
            <X className="w-5 h-5 sm:w-6 sm:h-6 opacity-60" />
          </button>
        </div>
        )}

        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* Sidebar */}
          <div className={`w-16 sm:w-64 border-r flex-shrink-0 ${darkMode ? 'border-gray-800/60' : 'border-gray-200/60'} p-2 sm:p-6 overflow-y-auto`}>
            <nav className="space-y-1 sm:space-y-2">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`w-full flex items-center space-x-3 px-2 sm:px-4 py-2 sm:py-3 rounded-xl text-left transition-colors ${
                    activeTab === tab.id
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                      : 'hover:bg-gray-500/10'
                  }`}
                  title={tab.label}
                >
                  <tab.icon className="w-4 h-4 sm:w-5 sm:h-5 flex-shrink-0" />
                  <span className="font-medium hidden sm:inline truncate">{tab.label}</span>
                </button>
              ))}
            </nav>

            {/* Memory Status */}
            <div className={`mt-6 p-4 rounded-xl border hidden sm:block ${
              darkMode 
                ? 'bg-gray-900/50 border-gray-800/60' 
                : 'bg-white/80 border-gray-200/60'
            }`}>
              <h4 className="font-medium mb-2">Memory Status</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span>Sessions:</span>
                  <span className="text-teal-400">{memoryStats.totalSessions}</span>
                </div>
                <div className="flex justify-between">
                  <span>Messages:</span>
                  <span className="text-green-400">{memoryStats.totalMessages}</span>
                </div>
                <div className="flex justify-between">
                  <span>Messages/session:</span>
                  <span className="text-emerald-400">{memoryStats.avgMessagesPerSession}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Main Content */}
          <div className="flex-1 overflow-y-auto p-4 sm:p-8">
            {isLoading && (
              <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-60">
                <div className={`p-6 rounded-2xl ${cardClasses} flex items-center space-x-3`}>
                  <RefreshCw className="w-6 h-6 animate-spin text-emerald-500" />
                  <span>Loading memory data...</span>
                </div>
              </div>
            )}
            {renderContent()}
          </div>
        </div>

        {/* Confirmation Dialog */}
        {showConfirmDialog && (
          <div className="fixed inset-0 z-70 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className={`w-full max-w-md p-6 rounded-2xl shadow-2xl border ${
              darkMode 
                ? 'bg-gray-950/98 text-gray-100 border-gray-800/60' 
                : 'bg-white/95 text-gray-900 border-gray-200/60'
            }`}>
              <div className="flex items-center space-x-3 mb-4">
                <div className="w-12 h-12 rounded-full bg-red-500/20 flex items-center justify-center">
                  <Trash2 className="w-6 h-6 text-red-500" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold">Confirm Session Deletion</h3>
                  <p className="text-sm opacity-60">This action cannot be undone</p>
                </div>
              </div>
              
              <p className="text-sm mb-6 opacity-80">
                Are you sure you want to clear this session? All conversation history will be permanently deleted.
              </p>
              
              <div className="flex flex-col sm:flex-row space-y-3 sm:space-y-0 sm:space-x-3">
                <button
                  onClick={() => {
                    setShowConfirmDialog(false);
                    setSessionToDelete(null);
                  }}
                  className="flex-1 py-3 px-4 rounded-xl border border-gray-500/50 hover:bg-gray-500/10 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleConfirmDelete}
                  disabled={isLoading}
                  className="flex-1 py-3 px-4 rounded-xl bg-red-500 hover:bg-red-600 text-white transition-colors disabled:opacity-50"
                >
                  {isLoading ? 'Deleting...' : 'Delete Session'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ConversationMemory;
