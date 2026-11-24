import React from 'react';
import { formatMath } from '../../lib/mathText';

/**
 * Minimal, safe Markdown renderer for assistant answers.
 *
 * Everything is built as React nodes — no HTML is ever injected — so model
 * output cannot add markup or scripts. Links are limited to http(s). Only
 * explicit Markdown constructs are interpreted: a hyphen inside a sentence is
 * left alone, and only lines that *start* with "- ", "* ", "• " or "1. "
 * become list items.
 *
 * Supported: paragraphs (single newlines kept as line breaks), # headings,
 * bullet / numbered lists with nesting by indentation, fenced code blocks
 * (an unclosed fence while streaming renders as code), pipe tables,
 * blockquotes, **bold**, *emphasis*, `inline code`, [text](https://link),
 * bare URLs and simple formulas (\( \frac{a}{b} \) shown as "a / b").
 */

const FENCE = /^\s*```([\w+-]*)\s*$/;
const HEADING = /^(#{1,4})\s+(.+?)\s*#*\s*$/;
const LIST_ITEM = /^(\s*)([-*•]|\d+[.)])\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

const splitRow = (line) => {
  let row = line.trim();
  if (row.startsWith('|')) row = row.slice(1);
  if (row.endsWith('|')) row = row.slice(0, -1);
  return row.split('|').map((cell) => cell.trim());
};

const isBlockStart = (line, next) =>
  FENCE.test(line) ||
  HEADING.test(line) ||
  LIST_ITEM.test(line) ||
  QUOTE.test(line) ||
  (line.includes('|') && next !== undefined && TABLE_RULE.test(next) && next.includes('-'));

export function parseBlocks(source) {
  const lines = String(source ?? '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i += 1;
      continue;
    }

    const fence = line.match(FENCE);
    if (fence) {
      const code = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i])) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1; // closing fence (absent while streaming)
      blocks.push({ type: 'code', lang: fence[1], text: code.join('\n') });
      continue;
    }

    if (line.includes('|') && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      const head = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
        rows.push(splitRow(lines[i]));
        i += 1;
      }
      blocks.push({ type: 'table', head, rows });
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] });
      i += 1;
      continue;
    }

    if (QUOTE.test(line)) {
      const quoted = [];
      while (i < lines.length && QUOTE.test(lines[i])) {
        quoted.push(lines[i].match(QUOTE)[1]);
        i += 1;
      }
      blocks.push({ type: 'quote', text: quoted.join('\n') });
      continue;
    }

    if (LIST_ITEM.test(line)) {
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(LIST_ITEM);
        if (m) {
          items.push({
            indent: m[1].replace(/\t/g, '  ').length,
            ordered: /\d/.test(m[2]),
            text: m[3]
          });
          i += 1;
        } else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) {
          // Hard-wrapped continuation of the previous item.
          items[items.length - 1].text += `\n${lines[i].trim()}`;
          i += 1;
        } else {
          break;
        }
      }
      blocks.push({ type: 'list', items });
      continue;
    }

    const para = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i], lines[i + 1])) {
      para.push(lines[i]);
      i += 1;
    }
    blocks.push({ type: 'paragraph', text: para.join('\n') });
  }

  return blocks;
}

// Build a nested tree out of flat items using their indentation.
function nestList(items) {
  const root = { children: [], indent: -1 };
  const stack = [root];
  items.forEach((item) => {
    const node = { ...item, children: [] };
    while (stack.length > 1 && item.indent <= stack[stack.length - 1].indent) stack.pop();
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  });
  return root.children;
}

// Groups: 1 code, 2 bold, 3-5 link, 6 bare URL, 7 formula (\( \), \[ \], $$ $$),
// 8 *emphasis* (no space just inside the asterisks, so "5 * 3 * 2" stays text).
const INLINE =
  /(`[^`\n]+`)|(\*\*[^*\n]+?\*\*)|(\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\))|(https?:\/\/[^\s<>()]*[^\s<>().,;:!?'"])|(\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]|\$\$[\s\S]+?\$\$)|(\*(?![\s*])[^*\n]+?(?<!\s)\*)/g;

// Models put U+202F (narrow no-break space) between ordinary words, which
// leaves a line no break opportunity: browsers then split words mid-way
// ("appr|oval"). Display it as a normal space, except after a digit, where a
// no-break space keeps "99.9 %" and "450 ms" together.
export const breakableSpaces = (text) =>
  String(text ?? '').replace(/(\d?) /g, (_, digit) => (digit ? `${digit} ` : ' '));

export function renderInline(text, keyPrefix = 'i') {
  const out = [];
  let last = 0;
  let n = 0;
  const source = String(text ?? '');
  let match;
  INLINE.lastIndex = 0;

  const pushText = (raw) => {
    const chunk = breakableSpaces(raw);
    if (!chunk) return;
    chunk.split('\n').forEach((part, idx) => {
      if (idx > 0) out.push(<br key={`${keyPrefix}-br-${n++}`} />);
      if (part) out.push(part);
    });
  };

  while ((match = INLINE.exec(source)) !== null) {
    pushText(source.slice(last, match.index));
    const key = `${keyPrefix}-${n++}`;
    if (match[1]) {
      out.push(<code key={key}>{match[1].slice(1, -1)}</code>);
    } else if (match[2]) {
      out.push(<strong key={key}>{breakableSpaces(match[2].slice(2, -2))}</strong>);
    } else if (match[3]) {
      out.push(
        <a key={key} href={match[5]} target="_blank" rel="noopener noreferrer">
          {breakableSpaces(match[4])}
        </a>
      );
    } else if (match[6]) {
      out.push(
        <a key={key} href={match[6]} target="_blank" rel="noopener noreferrer">
          {match[6]}
        </a>
      );
    } else if (match[7]) {
      out.push(
        <span key={key} className="fs-math">{formatMath(match[7].slice(2, -2))}</span>
      );
    } else if (match[8]) {
      out.push(<em key={key}>{breakableSpaces(match[8].slice(1, -1))}</em>);
    }
    last = match.index + match[0].length;
  }
  pushText(source.slice(last));
  return out;
}

function renderList(nodes, keyPrefix) {
  const ordered = nodes[0]?.ordered;
  const Tag = ordered ? 'ol' : 'ul';
  return (
    <Tag key={keyPrefix}>
      {nodes.map((node, idx) => (
        <li key={`${keyPrefix}-${idx}`}>
          {renderInline(node.text, `${keyPrefix}-${idx}`)}
          {node.children.length > 0 && renderList(node.children, `${keyPrefix}-${idx}-n`)}
        </li>
      ))}
    </Tag>
  );
}

export function MessageContent({ text }) {
  const blocks = parseBlocks(text);
  return (
    <div className="fs-md">
      {blocks.map((block, idx) => {
        const key = `b${idx}`;
        switch (block.type) {
          case 'code':
            return (
              <pre key={key} tabIndex={0} aria-label={block.lang ? `${block.lang} code` : 'Code'}>
                <code>{block.text}</code>
              </pre>
            );
          case 'table':
            return (
              <div key={key} className="fs-md-table" tabIndex={0} role="region" aria-label="Table">
                <table>
                  <thead>
                    <tr>
                      {block.head.map((cell, c) => (
                        <th key={c} scope="col">{renderInline(cell, `${key}-h${c}`)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, r) => (
                      <tr key={r}>
                        {row.map((cell, c) => (
                          <td key={c}>{renderInline(cell, `${key}-${r}-${c}`)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case 'heading': {
            const Tag = `h${Math.min(block.level + 1, 4)}`;
            return <Tag key={key}>{renderInline(block.text, key)}</Tag>;
          }
          case 'quote':
            return <blockquote key={key}>{renderInline(block.text, key)}</blockquote>;
          case 'list':
            return renderList(nestList(block.items), key);
          default:
            return <p key={key}>{renderInline(block.text, key)}</p>;
        }
      })}
    </div>
  );
}

export default MessageContent;
