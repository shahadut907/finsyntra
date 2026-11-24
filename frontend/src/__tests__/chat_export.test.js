/**
 * Chat PDF export: the transcript is rendered with the chat's own Markdown
 * renderer (so tables, lists, emphasis and formulas are formatted, never
 * printed as raw Markdown) and printed by the browser, which shapes Bangla.
 */
import React from 'react';
import { render } from '@testing-library/react';
import MessageContent from '../components/chat/MessageContent';
import { formatMath } from '../lib/mathText';
import { ChatExportDocument, displaySourceName, exportChatToPdf, PRINT_CSS } from '../lib/exportPdf';

const ANSWER = [
  '**Harbor API Service Targets**',
  '- **Monthly availability:** 99.9 %',
  '- **p95 request latency:** < 450 ms',
  '',
  '| Severity | Acknowledgement |',
  '|----------|-----------------|',
  '| **Severity 1** | Within **10 minutes** |',
  '',
  'Margin: \\( \\frac{840,000}{3,200,000} = 0.2625 \\) → *26.25 %*'
].join('\n');

const MESSAGES = [
  { id: 'u1', sender: 'user', text: 'Harbor API-এর service targets বুঝিয়ে বলো।', timestamp: '2026-11-02T07:57:29Z' },
  {
    id: 'a1',
    sender: 'assistant',
    text: ANSWER,
    timestamp: '2026-11-02T07:57:31Z',
    sources: [
      'FinSyntra_Cedarbridge_Engineering_b2e479ccd20540f196ca6cc6c749e38d.pdf',
      'FinSyntra_Cedarbridge_Engineering_b2e479ccd20540f196ca6cc6c749e38d.pdf'
    ]
  }
];

describe('formatMath', () => {
  test('renders fractions and operators as readable text', () => {
    expect(formatMath('\\frac{840,000}{3,200,000} = 0.2625')).toBe('840,000 / 3,200,000 = 0.2625');
    expect(formatMath('90 \\div 18{,}000 \\times 100 \\approx 0.5\\%')).toBe('90 ÷ 18,000 × 100 ≈ 0.5%');
    expect(formatMath('\\frac{\\text{spend}}{\\text{leads}}')).toBe('spend / leads');
  });
});

describe('MessageContent formulas and emphasis', () => {
  test('formula spans and *emphasis* are formatted, arithmetic asterisks are not', () => {
    const { container } = render(<MessageContent text={'x \\( \\frac{1}{2} \\) and *note* but 5 * 3 * 2'} />);
    expect(container.querySelector('.fs-math').textContent).toBe('1 / 2');
    expect(container.querySelector('em').textContent).toBe('note');
    expect(container.textContent).toContain('5 * 3 * 2');
    expect(container.textContent).not.toContain('\\frac');
  });
});

describe('ChatExportDocument', () => {
  test('renders Markdown structure, Bangla text and readable source names', () => {
    const { container } = render(
      <ChatExportDocument messages={MESSAGES} currentUserName="Demo CEO" tenant="FinSyntra Technologies" department="Executive" />
    );
    const text = container.textContent;
    // structure instead of raw Markdown
    expect(container.querySelectorAll('table th')).toHaveLength(2);
    expect(container.querySelector('td strong').textContent).toBe('Severity 1');
    expect(container.querySelectorAll('.fsx-ai li').length).toBeGreaterThanOrEqual(2);
    expect(text).not.toMatch(/\*\*|\|---/);
    expect(text).toContain('840,000 / 3,200,000 = 0.2625');
    // content preserved exactly, including boundaries and Bangla
    expect(text).toContain('< 450 ms');
    expect(text).toContain('Harbor API-এর service targets বুঝিয়ে বলো।');
    expect(container.querySelector('.fsx-user').getAttribute('lang')).toBe('bn');
    // duplicate sources collapse; storage suffix removed; header values are not truncated
    expect([...container.querySelectorAll('.fsx-sources li')].map((li) => li.textContent))
      .toEqual(['FinSyntra_Cedarbridge_Engineering.pdf']);
    expect(text).toContain('FinSyntra Technologies');
  });

  test('user text is shown verbatim, never as markup', () => {
    const { container } = render(
      <ChatExportDocument messages={[{ sender: 'user', text: '<b>x</b> **y**' }]} />
    );
    expect(container.querySelector('b')).toBeNull();
    expect(container.querySelector('.fsx-plain').textContent).toBe('<b>x</b> **y**');
  });

  test('displaySourceName strips only the storage suffix', () => {
    expect(displaySourceName('Report_0123456789abcdef0123456789abcdef.pdf')).toBe('Report.pdf');
    expect(displaySourceName({ name: 'plain.md' })).toBe('plain.md');
  });

  test('print CSS paginates and wraps instead of clipping', () => {
    expect(PRINT_CSS).toMatch(/@page/);
    expect(PRINT_CSS).toMatch(/counter\(page\)/);
    expect(PRINT_CSS).toMatch(/overflow-wrap: anywhere/);
    expect(PRINT_CSS).toMatch(/thead \{ display: table-header-group/);
  });
});

describe('exportChatToPdf', () => {
  test('prints a temporary transcript and restores the page afterwards', async () => {
    const print = jest.spyOn(window, 'print').mockImplementation(() => {
      expect(document.documentElement.classList.contains('fs-printing')).toBe(true);
      expect(document.getElementById('fs-print-root').textContent).toContain('Severity 1');
      expect(document.title).toMatch(/^finsyntra-chat-\d{4}-\d{2}-\d{2}-\d{6}$/);
      window.dispatchEvent(new Event('afterprint'));
    });
    document.title = 'FinSyntra AI';
    await expect(exportChatToPdf({ messages: MESSAGES, fileName: 'finsyntra-chat' })).resolves.toBe(true);
    expect(print).toHaveBeenCalledTimes(1);
    expect(document.getElementById('fs-print-root')).toBeNull();
    expect(document.getElementById('fs-print-style')).toBeNull();
    expect(document.documentElement.classList.contains('fs-printing')).toBe(false);
    expect(document.title).toBe('FinSyntra AI');
    print.mockRestore();
  });

  test('does nothing without messages', async () => {
    const print = jest.spyOn(window, 'print').mockImplementation(() => {});
    await expect(exportChatToPdf({ messages: [] })).resolves.toBe(false);
    expect(print).not.toHaveBeenCalled();
    print.mockRestore();
  });
});

describe('breakable spaces', () => {
  test('narrow no-break spaces between words become normal spaces; number-unit pairs stay together', () => {
    const { container } = render(<MessageContent text={'approval or permission **99.9 %** target'} />);
    expect(container.textContent).toBe('approval or permission 99.9 % target');
  });
});
