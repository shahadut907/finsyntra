// Friendly labels for role codes sent by the backend (e.g. "c_level").
const ROLE_LABELS = {
  admin: 'Admin',
  c_level: 'CEO',
  employee: 'Employee',
  finance: 'Finance',
  hr: 'HR',
  engineering: 'Engineering',
  marketing: 'Marketing'
};

/**
 * Public-demo identities are named "Demo <Role>" (e.g. "Demo CEO"); show
 * "CEO", "Finance", etc. by dropping a leading "Demo" token.
 */
export function displayName(user) {
  const parts = (user?.name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length > 1 && parts[0].toLowerCase() === 'demo') parts.shift();
  return parts.join(' ') || user?.email?.split('@')[0] || 'User';
}

export function roleLabel(user) {
  const role = user?.role;
  if (!role) return '';
  return ROLE_LABELS[String(role).toLowerCase()] || role;
}

/** Mirrors the backend/AdminRoute check: admin and c_level may open /admin. */
export function canAccessAdmin(user) {
  const role = String(user?.role || '').toLowerCase();
  return role === 'admin' || role === 'c_level';
}
