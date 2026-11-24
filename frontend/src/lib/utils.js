import { clsx } from "clsx";

/**
 * Utility function to merge class names
 */
export function cn(...inputs) {
  return clsx(inputs);
}

/**
 * Parse a server timestamp. The API serialises naive UTC datetimes (no zone
 * designator), which `new Date()` would otherwise read as local time.
 */
function parseServerDate(date) {
  if (typeof date === 'string' && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(date) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(date)) {
    return new Date(date.replace(' ', 'T') + 'Z');
  }
  return new Date(date);
}

/**
 * Format date to human readable string
 */
export function formatDate(date) {
  if (!date) return '';
  
  const now = new Date();
  const inputDate = parseServerDate(date);
  const diffInMs = now - inputDate;
  const diffInMinutes = Math.floor(diffInMs / 60000);
  const diffInHours = Math.floor(diffInMs / 3600000);
  const diffInDays = Math.floor(diffInMs / 86400000);

  if (diffInMinutes < 1) return 'Just now';
  if (diffInMinutes < 60) return `${diffInMinutes}m ago`;
  if (diffInHours < 24) return `${diffInHours}h ago`;
  if (diffInDays < 7) return `${diffInDays}d ago`;
  
  return inputDate.toLocaleDateString();
}

/**
 * Format file size to human readable string
 */
export function formatFileSize(bytes) {
  if (!bytes) return '0 B';
  
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${sizes[i]}`;
}

/**
 * Truncate text with ellipsis
 */
export function truncate(text, length = 100) {
  if (!text || text.length <= length) return text;
  return text.slice(0, length) + '...';
}

/**
 * Debounce function
 */
export function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * Get initials from name
 */
export function getInitials(name) {
  if (!name) return '';
  return name
    .split(' ')
    .map(word => word[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

/**
 * Generate random ID
 */
export function generateId() {
  return Math.random().toString(36).substr(2, 9);
}

/**
 * Check if user has permission
 */
export function hasPermission(userRole, requiredRoles) {
  if (!requiredRoles || requiredRoles.length === 0) return true;
  if (!userRole) return false;
  
  // Admin and c_level have access to everything
  if (userRole === 'admin' || userRole === 'c_level') return true;
  
  return requiredRoles.includes(userRole);
}

/**
 * Get role display information
 */
export function getRoleInfo(role) {
  const roleMap = {
    'employee': { 
      name: 'General Employee', 
      color: 'blue',
      gradient: 'from-blue-500 to-cyan-500'
    },
    'engineering': { 
      name: 'Engineering', 
      color: 'green',
      gradient: 'from-emerald-500 to-teal-500'
    },
    'finance': { 
      name: 'Finance', 
      color: 'purple',
      gradient: 'from-violet-500 to-indigo-500'
    },
    'marketing': { 
      name: 'Marketing', 
      color: 'orange',
      gradient: 'from-orange-500 to-pink-500'
    },
    'hr': { 
      name: 'Human Resources', 
      color: 'pink',
      gradient: 'from-pink-500 to-rose-500'
    },
    'c_level': { 
      name: 'C-Level Executive', 
      color: 'yellow',
      gradient: 'from-amber-500 to-orange-500'
    },
    'admin': { 
      name: 'Administrator', 
      color: 'red',
      gradient: 'from-red-500 to-pink-500'
    }
  };
  
  return roleMap[role] || roleMap['employee'];
}

/**
 * Format confidence score
 */
export function formatConfidence(score) {
  if (score >= 0.8) return { level: 'high', label: 'High', color: 'success' };
  if (score >= 0.6) return { level: 'medium', label: 'Medium', color: 'warning' };
  return { level: 'low', label: 'Low', color: 'danger' };
}

/**
 * Safe JSON parse
 */
export function safeJsonParse(str, fallback = null) {
  try {
    return JSON.parse(str);
  } catch {
    return fallback;
  }
}

/**
 * Download file
 */
export function downloadFile(data, filename, type = 'application/json') {
  const file = new Blob([data], { type });
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Copy to clipboard
 */
export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for older browsers
    const textArea = document.createElement('textarea');
    textArea.value = text;
    document.body.appendChild(textArea);
    textArea.select();
    const result = document.execCommand('copy');
    document.body.removeChild(textArea);
    return result;
  }
}

/**
 * Format time in a compact format for conversation timestamps
 */
export function formatTime(date) {
  if (!date) return '';
  const now = new Date();
  const target = parseServerDate(date);
  const diffMs = now - target;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 7) return `${diffDays}d`;
  
  return target.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}