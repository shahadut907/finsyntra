import React, { useCallback, useEffect, useState } from 'react';

const LIMIT_FIELDS = [
  { key: 'visitor_daily_limit', label: 'Messages per visitor / day' },
  { key: 'ip_daily_limit', label: 'Messages per network (IP) / day' },
  { key: 'global_daily_limit', label: 'Messages, all visitors / day' },
  { key: 'daily_token_budget', label: 'Daily token budget (total)' },
  { key: 'super_admin_token_reserve', label: 'Reserved for Super Admin (tokens)' },
];

const RESET_SCOPES = [
  { value: 'visitors', label: 'Visitor and network counters' },
  { value: 'global_messages', label: 'Global message counter' },
  { value: 'all_messages', label: 'All message counters' },
];

const errorText = async (response, fallback) => {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === 'string') return detail;
    return detail?.message || fallback;
  } catch {
    return fallback;
  }
};

const fmt = (n) => Number(n ?? 0).toLocaleString();
const when = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString([], { hour: 'numeric', minute: '2-digit', month: 'short', day: 'numeric' });
};

const Meter = ({ label, used, total, note }) => {
  const pct = total ? Math.min(100, Math.round((100 * used) / total)) : 0;
  return (
    <div className="p-4 glass-card" data-testid={`meter-${label}`}>
      <div className="flex items-baseline justify-between">
        <span className="text-sm opacity-80">{label}</span>
        <span className="text-sm font-semibold">{fmt(used)} / {fmt(total)}</span>
      </div>
      <div className="fs-usage-bar" style={{ width: '100%', height: 6, marginTop: 8 }} role="progressbar"
        aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <span style={{ width: `${pct}%` }} />
      </div>
      {note && <p className="text-xs opacity-70 mt-2">{note}</p>}
    </div>
  );
};

/**
 * Super Admin "Usage & Controls" section of the Admin Dashboard. Rendered only
 * for ``user.is_super_admin`` (a display hint); every request below is
 * authorised again by the backend, which rejects anyone else with 403.
 */
export const UsageControls = ({ apiCall, addNotification }) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [form, setForm] = useState({});
  const [dirty, setDirty] = useState(false);
  const [scope, setScope] = useState('visitors');
  const [pauseMinutes, setPauseMinutes] = useState('60');
  const [pauseMessage, setPauseMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const response = await apiCall('/admin/demo-usage');
      if (!response.ok) {
        setError(await errorText(response, 'Could not load usage.'));
        return;
      }
      const body = await response.json();
      setData(body);
      setError('');
      setForm((prev) => (dirty ? prev : Object.fromEntries(
        LIMIT_FIELDS.map(({ key }) => [key, String(body.config[key])]))));
    } catch {
      setError('Could not load usage.');
    }
  }, [apiCall, dirty]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [load]);

  const send = async (path, method, body, success) => {
    setBusy(true);
    try {
      const response = await apiCall(path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        addNotification?.(await errorText(response, 'The change was rejected.'), 'error');
        return false;
      }
      addNotification?.(success, 'success');
      setDirty(false);
      await load();
      return true;
    } catch {
      addNotification?.('Request failed. Please try again.', 'error');
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return <p className="text-sm opacity-70">{error || 'Loading usage…'}</p>;
  }

  const { messages, tokens, config, public_access: access } = data;
  const bounds = config.bounds;
  const saveLimits = () => {
    const changes = {};
    LIMIT_FIELDS.forEach(({ key }) => {
      const value = Number(form[key]);
      if (Number.isInteger(value) && value !== config[key]) changes[key] = value;
    });
    if (!Object.keys(changes).length) {
      addNotification?.('No limit changes to save.', 'info');
      return;
    }
    send('/admin/demo-usage/limits', 'PUT', changes, 'Limits updated.');
  };
  const restoreDefaults = () => {
    const nulls = Object.fromEntries(config.overridden.map((key) => [key, null]));
    if (!config.overridden.length) return;
    send('/admin/demo-usage/limits', 'PUT', nulls, 'Defaults restored.');
  };

  return (
    <div className="space-y-6" data-testid="usage-controls">
      <div className={`p-4 glass-card flex flex-wrap items-center justify-between gap-3 ${access.paused ? 'border-red-400' : ''}`}>
        <div>
          <h3 className="text-lg font-semibold">Public demo access</h3>
          <p className="text-sm opacity-80" data-testid="access-state">
            {access.paused
              ? `Paused${access.until ? ` until ${when(access.until)}` : ''}. Your Super Admin chat still works.`
              : 'Open to visitors.'}
          </p>
        </div>
        <span className="text-sm opacity-80">Resets {when(data.resets_at)}</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Meter label="Messages today" used={messages.used} total={messages.limit}
          note={`${fmt(messages.remaining)} remaining`} />
        <Meter label="Public tokens" used={tokens.public_used} total={tokens.public_cap}
          note={`${fmt(tokens.public_remaining)} remaining of the public share`} />
        <Meter label="Reserved tokens (Super Admin)" used={tokens.admin_used} total={tokens.admin_reserve}
          note={`${fmt(tokens.admin_remaining)} remaining; visitors cannot spend these`} />
        <div className="p-4 glass-card text-sm space-y-1">
          <div className="flex justify-between"><span className="opacity-80">Active AI requests</span>
            <strong data-testid="active-requests">{data.active_requests}</strong></div>
          <div className="flex justify-between"><span className="opacity-80">Visitors today</span><strong>{data.unique_visitors_today}</strong></div>
          <div className="flex justify-between"><span className="opacity-80">Networks today</span><strong>{data.unique_networks_today}</strong></div>
          <div className="flex justify-between"><span className="opacity-80">Total daily token budget</span><strong>{fmt(tokens.daily_budget)}</strong></div>
          <div className="flex justify-between"><span className="opacity-80">Fixed safety limits</span>
            <strong>{config.fixed.per_ip_per_minute}/min per IP, {config.fixed.max_concurrent_ai} concurrent</strong></div>
        </div>
      </div>

      <div className="p-4 glass-card space-y-4">
        <h3 className="text-lg font-semibold">Usage limits</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {LIMIT_FIELDS.map(({ key, label }) => (
            <label key={key} className="block text-sm">
              <span className="opacity-80">{label}</span>
              <input
                type="number"
                className="mt-1 w-full px-3 py-2 rounded-lg bg-transparent border border-current/30"
                min={bounds[key].min}
                max={bounds[key].max}
                value={form[key] ?? ''}
                onChange={(e) => { setDirty(true); setForm({ ...form, [key]: e.target.value }); }}
                aria-label={label}
              />
              <span className="text-xs opacity-60">
                {fmt(bounds[key].min)}–{fmt(bounds[key].max)}{config.overridden.includes(key) ? ' · customised' : ''}
              </span>
            </label>
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          <button type="button" className="px-3 py-2 glass-btn glass-btn-blue" disabled={busy || !dirty} onClick={saveLimits}>
            Save limits
          </button>
          <button type="button" className="px-3 py-2 glass-btn glass-btn-ghost" disabled={busy || !config.overridden.length}
            onClick={restoreDefaults}>
            Restore defaults
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="p-4 glass-card space-y-3">
          <h3 className="text-lg font-semibold">Reset message counters</h3>
          <p className="text-xs opacity-70">Clears today's message counts only. Token usage mirrors the real Groq quota and is never reset.</p>
          <select className="w-full px-3 py-2 rounded-lg bg-transparent border border-current/30" value={scope}
            onChange={(e) => setScope(e.target.value)} aria-label="Counters to reset">
            {RESET_SCOPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <button type="button" className="px-3 py-2 glass-btn glass-btn-orange" disabled={busy}
            onClick={() => window.confirm('Reset these counters for today?')
              && send('/admin/demo-usage/reset', 'POST', { scope }, 'Counters reset.')}>
            Reset counters
          </button>
        </div>

        <div className="p-4 glass-card space-y-3">
          <h3 className="text-lg font-semibold">Pause or resume the public demo</h3>
          {access.paused ? (
            <button type="button" className="px-3 py-2 glass-btn glass-btn-green" disabled={busy}
              onClick={() => send('/admin/demo-usage/access', 'PUT', { enabled: true }, 'Public demo resumed.')}>
              Resume public demo
            </button>
          ) : (
            <>
              <label className="block text-sm">
                <span className="opacity-80">Pause for (minutes, up to 10,080)</span>
                <input type="number" min="1" max="10080" value={pauseMinutes}
                  className="mt-1 w-full px-3 py-2 rounded-lg bg-transparent border border-current/30"
                  onChange={(e) => setPauseMinutes(e.target.value)} aria-label="Pause minutes" />
              </label>
              <input type="text" maxLength={300} value={pauseMessage} placeholder="Message shown to visitors (optional)"
                className="w-full px-3 py-2 rounded-lg bg-transparent border border-current/30"
                onChange={(e) => setPauseMessage(e.target.value)} aria-label="Pause message" />
              <button type="button" className="px-3 py-2 glass-btn glass-btn-red" disabled={busy}
                onClick={() => send('/admin/demo-usage/access', 'PUT', {
                  enabled: false,
                  pause_minutes: Number(pauseMinutes) || null,
                  message: pauseMessage.trim() || null,
                }, 'Public demo paused.')}>
                Pause public demo
              </button>
            </>
          )}
        </div>
      </div>

      {data.history?.length > 0 && (
        <div className="p-4 glass-card">
          <h3 className="text-lg font-semibold mb-2">Last 7 days</h3>
          <table className="w-full text-sm">
            <thead><tr className="text-left opacity-70"><th>Day (UTC)</th><th>Messages</th><th>Public tokens</th></tr></thead>
            <tbody>
              {data.history.map((row) => (
                <tr key={row.day}><td>{row.day}</td><td>{fmt(row.messages)}</td><td>{fmt(row.tokens)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default UsageControls;
