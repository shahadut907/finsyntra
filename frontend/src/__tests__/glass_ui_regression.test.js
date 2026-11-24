/**
 * Regression tests for the glass UI refinement:
 *  - assistant answers render as safe Markdown (lists, code, tables) — no HTML
 *  - message surfaces never move or resize on hover (the old GlassCard wrapped
 *    framer-motion `whileHover={{ scale: 1.02, y: -2 }}`)
 *  - the shell keeps the composer in flow (no position: fixed overlays that
 *    covered the transcript) and owns a single viewport-height scroll region
 *  - the mobile navigation drawer is a real modal (Escape closes, focus returns)
 */

import React from 'react';
import fs from 'fs';
import path from 'path';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import MessageContent, { parseBlocks } from '../components/chat/MessageContent';
import ChatMessage from '../components/chat/ChatMessage';
import GlassCard from '../components/ui/GlassCard';
import ChatComposer from '../components/chat/ChatComposer';
import AppShell from '../components/layout/AppShell';

// Comments are stripped so a leading comment never becomes part of a selector.
const css = fs
  .readFileSync(path.join(__dirname, '../styles/glass.css'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '');

// Return the declaration blocks of every rule whose selector list includes `selector`.
const rulesFor = (selector) => {
  const blocks = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css)) !== null) {
    const selectors = m[1].split(',').map((s) => s.trim());
    if (selectors.includes(selector)) blocks.push(m[2]);
  }
  return blocks;
};

describe('MessageContent (safe Markdown)', () => {
  test('only lines that start with a marker become list items', () => {
    const { container } = render(
      <MessageContent text={'Totals - USD 5 - are fine.\n\n- first\n- second\n\n1. one\n2. two'} />
    );
    expect(container.querySelectorAll('ul > li')).toHaveLength(2);
    expect(container.querySelectorAll('ol > li')).toHaveLength(2);
    // the inline hyphens stay plain text in a paragraph
    expect(container.querySelector('p').textContent).toBe('Totals - USD 5 - are fine.');
  });

  test('renders nested lists, code fences, tables and Bangla text', () => {
    const text = [
      '- parent',
      '  - child',
      '',
      '```python',
      "print('hi')",
      '```',
      '',
      '| A | B |',
      '|---|---|',
      '| 1 | 2 |',
      '',
      'আন্তর্জাতিক ভ্রমণ'
    ].join('\n');
    const { container } = render(<MessageContent text={text} />);
    expect(container.querySelector('ul ul li').textContent).toBe('child');
    expect(container.querySelector('pre code').textContent).toBe("print('hi')");
    expect(container.querySelectorAll('table th')).toHaveLength(2);
    expect(container.textContent).toContain('আন্তর্জাতিক ভ্রমণ');
  });

  test('an unclosed fence while streaming still renders as code', () => {
    const blocks = parseBlocks('```js\nconst a = 1;');
    expect(blocks).toEqual([{ type: 'code', lang: 'js', text: 'const a = 1;' }]);
  });

  test('never injects HTML and only links http(s)', () => {
    const { container } = render(
      <MessageContent
        text={'<img src=x onerror=alert(1)> <script>alert(1)</script> [bad](javascript:alert(1)) [ok](https://example.com/a) **bold**'}
      />
    );
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    const links = [...container.querySelectorAll('a')];
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['https://example.com/a']);
    expect(links[0].getAttribute('rel')).toContain('noopener');
    expect(container.querySelector('strong').textContent).toBe('bold');
    expect(container.textContent).toContain('<script>alert(1)</script>');
  });
});

describe('message surfaces do not move on hover', () => {
  // framer-motion only applies `whileHover` transforms while the pointer is on
  // the element, so a render-time check cannot see them (the original bug
  // passed a "no inline style" assertion). Guard the source of everything on
  // the message render path instead.
  const MESSAGE_PATH = [
    '../components/ui/GlassCard.js',
    '../components/CategoryPill.js',
    '../components/chat/ChatMessage.jsx',
    '../components/chat/MessageContent.jsx',
    '../components/chat/ChatWelcome.jsx',
    '../components/DarkChatInterface.js'
  ];
  const HOVER_MOTION = /whileHover|whileTap|hover:scale|hover:-?translate|group-hover:scale|hover:rotate/;

  test.each(MESSAGE_PATH)('%s declares no hover/tap motion', (file) => {
    const source = fs.readFileSync(path.join(__dirname, file), 'utf8');
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    expect(code).not.toMatch(HOVER_MOTION);
  });

  test('GlassCard renders a plain element (no motion wrapper)', () => {
    const { container } = render(<GlassCard className="x">content</GlassCard>);
    expect(container.firstChild.tagName).toBe('DIV');
    const source = fs
      .readFileSync(path.join(__dirname, '../components/ui/GlassCard.js'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '');
    expect(source).not.toMatch(/framer-motion/);
  });

  test('ChatMessage bubble carries no inline transform styles', () => {
    const { container } = render(
      <ChatMessage
        message={{ id: 1, sender: 'assistant', text: 'hello', timestamp: new Date().toISOString(), sources: ['a.md', 'a.md'] }}
        userInitial="U"
      />
    );
    container.querySelectorAll('*').forEach((el) => {
      expect(el.getAttribute('style') || '').not.toMatch(/transform|scale/i);
    });
    // duplicate citations collapse to one chip
    expect(container.querySelectorAll('.fs-chip')).toHaveLength(1);
  });

  test('glass.css message rules never resize or move on hover', () => {
    const hoverRules = [...css.matchAll(/([^{}]*:hover[^{}]*)\{([^{}]*)\}/g)]
      .filter(([, sel]) => /\.fs-(bubble|msg|md|chip)/.test(sel));
    expect(hoverRules.length).toBeGreaterThan(0);
    hoverRules.forEach(([, , body]) => {
      expect(body).not.toMatch(/transform|scale|width|height|padding|margin|font-|letter-spacing|border-width/);
    });
    [...rulesFor('.fs-bubble'), ...rulesFor('.fs-msg'), ...rulesFor('.fs-msg-body')].forEach((body) => {
      expect(body).not.toMatch(/transform\s*:|scale\(/);
    });
  });
});

describe('layout: no fixed overlays over the transcript', () => {
  test('composer, header and thread are in normal flow; the shell owns one viewport', () => {
    [...rulesFor('.fs-composer-wrap'), ...rulesFor('.fs-composer'), ...rulesFor('.fs-header'), ...rulesFor('.fs-scroll')]
      .forEach((body) => expect(body).not.toMatch(/position\s*:\s*(fixed|absolute)/));

    const shell = rulesFor('.fs-app').join('\n');
    expect(shell).toMatch(/height\s*:\s*100dvh/);
    expect(shell).toMatch(/height\s*:\s*100vh/); // fallback before dvh
    expect(shell).toMatch(/overflow\s*:\s*hidden/);

    const scroller = rulesFor('.fs-scroll').join('\n');
    expect(scroller).toMatch(/min-height\s*:\s*0/);
    expect(scroller).toMatch(/overflow-y\s*:\s*auto/);
  });

  test('every translucent surface has an opaque fallback without backdrop-filter', () => {
    expect(css).toMatch(/@supports not \(\(backdrop-filter: blur\(1px\)\)/);
  });

  test('composer textarea grows to a cap then scrolls internally', () => {
    const body = rulesFor('.fs-composer textarea').join('\n');
    expect(body).toMatch(/max-height\s*:\s*200px/);
    expect(body).toMatch(/overflow-y\s*:\s*auto/);
  });
});

describe('ChatComposer keyboard behaviour', () => {
  const setup = (props = {}) => {
    const onSubmit = jest.fn();
    const onChange = jest.fn();
    render(<ChatComposer value="hello" onChange={onChange} onSubmit={onSubmit} {...props} />);
    return { onSubmit, onChange, box: screen.getByLabelText('Message') };
  };

  test('Enter sends, Shift+Enter does not', () => {
    const { onSubmit, box } = setup();
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  test('Enter during IME composition (Bangla) does not send', () => {
    const { onSubmit, box } = setup();
    fireEvent.keyDown(box, { key: 'Enter', isComposing: true });
    fireEvent.keyDown(box, { key: 'Enter', keyCode: 229 });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test('shows Stop while streaming and Send is disabled when empty', () => {
    const onStop = jest.fn();
    const { rerender } = render(
      <ChatComposer value="" onChange={() => {}} onSubmit={() => {}} onStop={onStop} isStreaming />
    );
    fireEvent.click(screen.getByLabelText('Stop response'));
    expect(onStop).toHaveBeenCalled();
    rerender(<ChatComposer value="" onChange={() => {}} onSubmit={() => {}} />);
    expect(screen.getByLabelText('Send message')).toBeDisabled();
  });
});

describe('mobile navigation drawer', () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    window.matchMedia = (query) => ({
      matches: /max-width:\s*899px/.test(query),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {}
    });
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  test('opens as a modal dialog, closes on Escape and returns focus to the opener', () => {
    render(
      <MemoryRouter>
        <AppShell user={{ name: 'Test User', role: 'employee' }} title="Chat">
          <p>content</p>
        </AppShell>
      </MemoryRouter>
    );

    const opener = screen.getByLabelText('Open navigation menu');
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole('dialog', { name: 'Navigation menu' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(document.activeElement, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Navigation menu' })).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  test('admin destination is only offered to admin and c_level roles', () => {
    const renderFor = (role) => {
      const view = render(
        <MemoryRouter>
          <AppShell user={{ name: 'U', role }} title="Chat">
            <p>x</p>
          </AppShell>
        </MemoryRouter>
      );
      fireEvent.click(screen.getByLabelText('Open navigation menu'));
      const has = !!screen.queryByRole('link', { name: 'Admin' });
      view.unmount();
      return has;
    };
    expect(renderFor('employee')).toBe(false);
    expect(renderFor('admin')).toBe(true);
    expect(renderFor('c_level')).toBe(true);
  });
});
