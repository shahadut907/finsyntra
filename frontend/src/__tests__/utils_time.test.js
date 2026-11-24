import { formatTime, formatDate } from '../lib/utils';

// The API serialises naive UTC datetimes (no "Z"); they must not be read as local time.
describe('server timestamp parsing', () => {
  const naiveUtc = (msAgo) => new Date(Date.now() - msAgo).toISOString().replace('Z', '');

  test('naive UTC timestamp from the API is treated as UTC', () => {
    expect(formatTime(naiveUtc(5 * 60000))).toBe('5m');
    expect(formatDate(naiveUtc(2 * 3600000))).toBe('2h ago');
  });

  test('timestamps with an explicit zone are unchanged', () => {
    expect(formatTime(new Date(Date.now() - 5 * 60000).toISOString())).toBe('5m');
  });
});
