import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Gauge } from 'lucide-react';
import { apiFetch } from '../../lib/apiClient';

export const DEMO_USAGE_REFRESH_EVENT = 'finsyntra:demo-usage-refresh';

const formatReset = (iso) => {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return '';
  return when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
};

const formatCountdown = (seconds) => {
  if (!Number.isFinite(seconds) || seconds <= 0) return 'soon';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${Math.max(m, 1)}m`;
};

/**
 * Daily public-demo allowance, shown beside the composer. Renders nothing for
 * private accounts (the endpoint reports ``enabled: false``) or when the
 * endpoint is unavailable. Counts come from the server; this never limits
 * anything client-side.
 */
export const DemoUsageMeter = ({ enabled = true }) => {
  const [usage, setUsage] = useState(null);
  const [open, setOpen] = useState(false);
  const mounted = useRef(true);

  const load = useCallback(async () => {
    try {
      const response = await apiFetch('/api/demo/usage');
      if (!response.ok) return;
      const body = await response.json();
      if (mounted.current) setUsage(body?.enabled ? body : null);
    } catch {
      /* the indicator is informational; stay silent */
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) return undefined;
    load();
    const refresh = () => load();
    window.addEventListener(DEMO_USAGE_REFRESH_EVENT, refresh);
    return () => {
      mounted.current = false;
      window.removeEventListener(DEMO_USAGE_REFRESH_EVENT, refresh);
    };
  }, [enabled, load]);

  if (!enabled || !usage) return null;

  const { used, limit, remaining, percent, resets_at: resetsAt, seconds_until_reset: seconds } = usage;
  const exhausted = remaining <= 0;
  const low = !exhausted && remaining <= 2;
  const tone = exhausted ? 'out' : low ? 'low' : 'ok';
  const label = exhausted
    ? 'Daily demo messages used up'
    : `${remaining} of ${limit} demo messages left today`;

  return (
    <div className={`fs-usage fs-usage--${tone}`} data-testid="demo-usage">
      <button
        type="button"
        className="fs-usage-btn"
        aria-expanded={open}
        aria-controls="fs-usage-panel"
        onClick={() => setOpen((v) => !v)}
      >
        <Gauge size={14} aria-hidden="true" />
        <span className="fs-usage-label">{label}</span>
        <span
          className="fs-usage-bar"
          role="progressbar"
          aria-label="Demo messages used today"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
        >
          <span style={{ width: `${percent}%` }} />
        </span>
      </button>
      {open && (
        <div className="fs-usage-panel" id="fs-usage-panel" role="status">
          <dl>
            <div><dt>Used today</dt><dd>{used} of {limit}</dd></div>
            <div><dt>Remaining</dt><dd>{remaining}</dd></div>
            <div><dt>Consumed</dt><dd>{percent}%</dd></div>
            <div><dt>Resets</dt><dd>{formatReset(resetsAt)} (in {formatCountdown(seconds)})</dd></div>
          </dl>
          {usage.shared_capacity_low && !exhausted && (
            <p>Shared demo capacity is running low, so you may have fewer messages than shown.</p>
          )}
          {exhausted && (
            <p>You can still browse your conversations. New messages unlock at the reset time.</p>
          )}
        </div>
      )}
    </div>
  );
};

export default DemoUsageMeter;
