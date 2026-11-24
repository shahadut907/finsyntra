"""
Professional PDF Export Service for FinSyntra AI Chat Conversations.
Uses WeasyPrint to generate branded, chat-bubble styled PDFs.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
import html
import logging

try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError, Exception) as e:
    # WeasyPrint may fail to import if native GTK/Pango libraries are missing
    WEASYPRINT_AVAILABLE = False
    HTML = None
    CSS = None
    FontConfiguration = None

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

logger = logging.getLogger(__name__)


class ChatPDFExporter:
    """Generate professional PDF exports of chat conversations."""

    def __init__(self):
        if WEASYPRINT_AVAILABLE:
            self.font_config = FontConfiguration()
        else:
            self.font_config = None
            logger.warning("WeasyPrint not available. PDF export will use fallback.")

    def export_chat(
        self,
        messages: List[Dict[str, Any]],
        session_title: str = "Chat Conversation",
        session_id: str = "",
        user_email: str = "",
        user_role: str = "",
        tenant_name: str = "FinSyntra",
        export_date: Optional[datetime] = None
    ) -> bytes:
        """
        Export chat messages to a professionally styled PDF.

        Args:
            messages: List of message dicts with 'message_type', 'content', 'timestamp'
            session_title: Title for the conversation
            session_id: Unique session identifier
            user_email: User who owns this conversation
            user_role: User's role for context
            tenant_name: Organization name
            export_date: When the export was generated

        Returns:
            PDF file as bytes
        """
        if not WEASYPRINT_AVAILABLE:
            # Fallback to simple text PDF
            return self._fallback_pdf(messages, session_title, session_id)

        export_date = export_date or datetime.utcnow()

        # Generate HTML
        html_content = self._generate_html(
            messages=messages,
            session_title=session_title,
            session_id=session_id,
            user_email=user_email,
            user_role=user_role,
            tenant_name=tenant_name,
            export_date=export_date
        )

        # Convert to PDF
        html_doc = HTML(string=html_content)
        css = CSS(string=self._get_css())

        pdf_bytes = html_doc.write_pdf(
            stylesheets=[css],
            font_config=self.font_config
        )

        return pdf_bytes

    def _generate_html(
        self,
        messages: List[Dict],
        session_title: str,
        session_id: str,
        user_email: str,
        user_role: str,
        tenant_name: str,
        export_date: datetime
    ) -> str:
        """Generate the HTML structure for the PDF."""

        # Convert messages to HTML
        messages_html = self._render_messages(messages, tenant_name)

        # Calculate stats
        total_messages = len(messages)
        user_messages = sum(1 for m in messages if m.get('message_type') == 'user')
        assistant_messages = total_messages - user_messages

        # Get conversation date range
        if messages:
            first_ts = messages[0].get('timestamp')
            last_ts = messages[-1].get('timestamp')
            first_msg = self._parse_timestamp(first_ts)
            last_msg = self._parse_timestamp(last_ts)
            if first_msg and last_msg:
                date_range = f"{first_msg.strftime('%B %d, %Y %I:%M %p')} - {last_msg.strftime('%I:%M %p')}"
            else:
                date_range = "Chat Session"
        else:
            date_range = "No messages"

        # Truncate session ID for display
        display_session_id = session_id[:8] + '...' if len(session_id) > 8 else session_id

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{html.escape(session_title)} - {html.escape(tenant_name)}</title>
</head>
<body>
    <!-- Header -->
    <header class="document-header">
        <div class="header-left">
            <div class="logo">
                <div class="logo-icon">
                    <svg width="36" height="36" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <rect width="36" height="36" rx="8" fill="#3B82F6"/>
                        <path d="M11 13L18 9L25 13V23L18 27L11 23V13Z" fill="white" fill-opacity="0.9"/>
                        <circle cx="18" cy="18" r="4" fill="#3B82F6"/>
                    </svg>
                </div>
                <div class="logo-text">
                    <span class="brand-name">{html.escape(tenant_name)}</span>
                    <span class="brand-tagline">AI Document Assistant</span>
                </div>
            </div>
        </div>
        <div class="header-right">
            <div class="export-badge">Chat Export</div>
        </div>
    </header>

    <!-- Document Title Section -->
    <section class="title-section">
        <h1 class="document-title">{html.escape(session_title)}</h1>
        <div class="meta-grid">
            <div class="meta-item">
                <span class="meta-label">Session ID</span>
                <span class="meta-value">{html.escape(display_session_id)}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">User</span>
                <span class="meta-value">{html.escape(user_email or 'N/A')}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Role</span>
                <span class="meta-value">{html.escape(user_role.replace('_', ' ').title() if user_role else 'N/A')}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Date</span>
                <span class="meta-value">{html.escape(date_range)}</span>
            </div>
        </div>
    </section>

    <!-- Stats Bar -->
    <section class="stats-bar">
        <div class="stat">
            <span class="stat-number">{total_messages}</span>
            <span class="stat-label">Total Messages</span>
        </div>
        <div class="stat">
            <span class="stat-number">{user_messages}</span>
            <span class="stat-label">User Queries</span>
        </div>
        <div class="stat">
            <span class="stat-number">{assistant_messages}</span>
            <span class="stat-label">AI Responses</span>
        </div>
        <div class="stat">
            <span class="stat-number">{export_date.strftime('%m/%d/%Y')}</span>
            <span class="stat-label">Exported</span>
        </div>
    </section>

    <!-- Conversation -->
    <section class="conversation">
        <h2 class="section-title">Conversation Transcript</h2>
        <div class="messages-container">
            {messages_html}
        </div>
    </section>

    <!-- Footer -->
    <footer class="document-footer">
        <div class="footer-left">
            <span class="confidential">CONFIDENTIAL</span>
            <span class="footer-text">This document contains proprietary information from {html.escape(tenant_name)}.</span>
        </div>
        <div class="footer-right">
            <span class="footer-text">Generated by {html.escape(tenant_name)} AI</span>
            <span class="footer-text">{export_date.strftime('%B %d, %Y at %I:%M %p UTC')}</span>
        </div>
    </footer>
</body>
</html>
        """

        return html_content

    def _render_messages(self, messages: List[Dict], tenant_name: str) -> str:
        """Render messages as styled chat bubbles."""
        html_parts = []

        for msg in messages:
            role = msg.get('message_type', 'user')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp')

            # Format timestamp
            time_str = ""
            parsed_ts = self._parse_timestamp(timestamp)
            if parsed_ts:
                time_str = parsed_ts.strftime('%I:%M %p')

            # Convert markdown to HTML for assistant messages
            if role == 'assistant':
                content_html = self._markdown_to_html(content)
                avatar_class = "avatar-assistant"
                avatar_text = "AI"
                message_class = "message assistant"
                sender_name = f"{tenant_name} AI"
            else:
                content_html = f"<p>{html.escape(content)}</p>"
                avatar_class = "avatar-user"
                avatar_text = "U"
                message_class = "message user"
                sender_name = "You"

            # Handle sources if present
            sources = msg.get('sources', [])
            sources_html = ""
            if sources and len(sources) > 0:
                source_items = "".join(f'<span class="source-tag">{html.escape(str(s))}</span>' for s in sources[:5])
                sources_html = f'<div class="sources-section"><span class="sources-label">Sources:</span> {source_items}</div>'

            html_parts.append(f"""
            <div class="{message_class}">
                <div class="{avatar_class}">{avatar_text}</div>
                <div class="message-content">
                    <div class="message-header">
                        <span class="sender-name">{sender_name}</span>
                        <span class="message-time">{time_str}</span>
                    </div>
                    <div class="message-body">
                        {content_html}
                        {sources_html}
                    </div>
                </div>
            </div>
            """)

        return '\n'.join(html_parts)

    def _parse_timestamp(self, timestamp) -> Optional[datetime]:
        """Parse timestamp from various formats."""
        if not timestamp:
            return None
        if isinstance(timestamp, datetime):
            return timestamp
        if isinstance(timestamp, str):
            try:
                # Handle ISO format with Z suffix
                ts = timestamp.replace('Z', '+00:00')
                return datetime.fromisoformat(ts)
            except (ValueError, AttributeError):
                pass
        return None

    def _markdown_to_html(self, text: str) -> str:
        """Convert markdown text to styled HTML."""
        if not text:
            return "<p></p>"

        if MARKDOWN_AVAILABLE:
            md = markdown.Markdown(extensions=['tables', 'fenced_code', 'nl2br'])
            html_content = md.convert(text)
        else:
            # Simple fallback: wrap in paragraphs and escape
            html_content = f"<p>{html.escape(text)}</p>"

        # Add custom styling for code blocks
        html_content = html_content.replace(
            '<code>', '<code class="inline-code">'
        )
        html_content = html_content.replace(
            '<pre>', '<pre class="code-block">'
        )

        return html_content

    def _get_css(self) -> str:
        """Return CSS styles for the PDF."""
        return """
        @page {
            size: A4;
            margin: 1.5cm 2cm;

            @top-right {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 9pt;
                color: #6B7280;
            }

            @bottom-center {
                content: "FinSyntra AI Chat Export";
                font-size: 9pt;
                color: #9CA3AF;
            }
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            font-size: 11pt;
            line-height: 1.6;
            color: #1F2937;
            background: #FFFFFF;
        }

        /* Header */
        .document-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 2px solid #E5E7EB;
            margin-bottom: 24px;
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo-icon svg {
            width: 40px;
            height: 40px;
        }

        .logo-text {
            display: flex;
            flex-direction: column;
        }

        .brand-name {
            font-size: 18pt;
            font-weight: 700;
            color: #1E3A5F;
        }

        .brand-tagline {
            font-size: 9pt;
            color: #6B7280;
        }

        .export-badge {
            background: linear-gradient(135deg, #3B82F6, #1D4ED8);
            color: white;
            padding: 6px 16px;
            border-radius: 20px;
            font-size: 10pt;
            font-weight: 600;
        }

        /* Title Section */
        .title-section {
            margin-bottom: 24px;
        }

        .document-title {
            font-size: 20pt;
            font-weight: 700;
            color: #111827;
            margin-bottom: 16px;
        }

        .meta-grid {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            background: #F9FAFB;
            padding: 16px;
            border-radius: 8px;
            border: 1px solid #E5E7EB;
        }

        .meta-item {
            display: flex;
            flex-direction: column;
            flex: 1;
        }

        .meta-label {
            font-size: 8pt;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #6B7280;
            margin-bottom: 4px;
        }

        .meta-value {
            font-size: 10pt;
            font-weight: 600;
            color: #111827;
        }

        /* Stats Bar */
        .stats-bar {
            display: flex;
            justify-content: space-between;
            background: linear-gradient(135deg, #1E3A5F 0%, #2D5A87 100%);
            padding: 16px 24px;
            border-radius: 8px;
            margin-bottom: 24px;
        }

        .stat {
            text-align: center;
            color: white;
        }

        .stat-number {
            display: block;
            font-size: 18pt;
            font-weight: 700;
        }

        .stat-label {
            font-size: 8pt;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            opacity: 0.8;
        }

        /* Conversation */
        .section-title {
            font-size: 14pt;
            font-weight: 600;
            color: #374151;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid #E5E7EB;
        }

        .messages-container {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        /* Messages */
        .message {
            display: flex;
            gap: 12px;
            page-break-inside: avoid;
        }

        .message.user {
            flex-direction: row-reverse;
        }

        .avatar-user, .avatar-assistant {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 12pt;
            flex-shrink: 0;
            color: white;
        }

        .avatar-user {
            background: linear-gradient(135deg, #8B5CF6, #6D28D9);
        }

        .avatar-assistant {
            background: linear-gradient(135deg, #10B981, #059669);
        }

        .message-content {
            flex: 1;
            max-width: 85%;
        }

        .message.user .message-content {
            text-align: right;
        }

        .message-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 4px;
        }

        .message.user .message-header {
            justify-content: flex-end;
        }

        .sender-name {
            font-weight: 600;
            font-size: 10pt;
            color: #374151;
        }

        .message-time {
            font-size: 8pt;
            color: #9CA3AF;
        }

        .message-body {
            background: #F3F4F6;
            padding: 12px 16px;
            border-radius: 12px;
            font-size: 10.5pt;
            line-height: 1.6;
        }

        .message.user .message-body {
            background: linear-gradient(135deg, #3B82F6, #2563EB);
            color: white;
            border-radius: 12px 12px 4px 12px;
        }

        .message.assistant .message-body {
            background: #F9FAFB;
            border: 1px solid #E5E7EB;
            border-radius: 12px 12px 12px 4px;
        }

        .message-body p {
            margin-bottom: 8px;
        }

        .message-body p:last-child {
            margin-bottom: 0;
        }

        .message-body ul, .message-body ol {
            margin-left: 20px;
            margin-bottom: 8px;
        }

        .message-body li {
            margin-bottom: 4px;
        }

        /* Sources */
        .sources-section {
            margin-top: 12px;
            padding-top: 8px;
            border-top: 1px dashed #D1D5DB;
        }

        .sources-label {
            font-size: 8pt;
            color: #6B7280;
            font-weight: 600;
        }

        .source-tag {
            display: inline-block;
            background: #FEF3C7;
            color: #92400E;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 8pt;
            margin: 4px 4px 0 0;
        }

        /* Code styling */
        .inline-code {
            background: #E5E7EB;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'SF Mono', Monaco, Consolas, monospace;
            font-size: 9pt;
        }

        .code-block {
            background: #1F2937;
            color: #F9FAFB;
            padding: 12px;
            border-radius: 8px;
            font-family: 'SF Mono', Monaco, Consolas, monospace;
            font-size: 9pt;
            overflow-x: auto;
            margin: 8px 0;
            white-space: pre-wrap;
        }

        /* Tables */
        .message-body table {
            width: 100%;
            border-collapse: collapse;
            margin: 8px 0;
            font-size: 9pt;
        }

        .message-body th, .message-body td {
            border: 1px solid #D1D5DB;
            padding: 8px;
            text-align: left;
        }

        .message-body th {
            background: #F3F4F6;
            font-weight: 600;
        }

        /* Footer */
        .document-footer {
            margin-top: 32px;
            padding-top: 16px;
            border-top: 1px solid #E5E7EB;
            display: flex;
            justify-content: space-between;
            font-size: 8pt;
            color: #6B7280;
        }

        .confidential {
            display: inline-block;
            background: #FEE2E2;
            color: #DC2626;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 7pt;
            margin-right: 8px;
        }

        .footer-right {
            text-align: right;
        }

        .footer-text {
            display: block;
        }

        /* Strong/Bold in messages */
        .message-body strong {
            font-weight: 600;
        }

        /* Blockquotes */
        .message-body blockquote {
            border-left: 3px solid #3B82F6;
            padding-left: 12px;
            margin: 8px 0;
            color: #4B5563;
            font-style: italic;
        }
        """

    def _fallback_pdf(self, messages: List[Dict], session_title: str, session_id: str) -> bytes:
        """Fallback to simple text-based PDF when WeasyPrint is not available."""
        import textwrap

        lines = [f"FinSyntra AI - Chat Export", "=" * 40, ""]
        lines.append(f"Session: {session_title}")
        lines.append(f"ID: {session_id}")
        lines.append(f"Exported: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("")
        lines.append("-" * 40)
        lines.append("")

        for msg in messages:
            role = msg.get('message_type', 'unknown').upper()
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')
            ts_str = ""
            parsed = self._parse_timestamp(timestamp)
            if parsed:
                ts_str = parsed.strftime('%I:%M %p')

            lines.append(f"[{role}] {ts_str}")
            if content:
                lines.extend(textwrap.wrap(content, width=80))
            lines.append("")

        lines.append("-" * 40)
        lines.append("CONFIDENTIAL - FinSyntra AI")

        return self._build_simple_pdf(lines)

    def _escape_pdf_text(self, text: str) -> str:
        """Escape special characters for PDF text."""
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def _build_simple_pdf(self, lines: List[str]) -> bytes:
        """Basic PDF generator without external dependencies (fallback)."""
        if not lines:
            lines = ["(No content)"]

        lines_per_page = 45
        pages = [lines[i:i + lines_per_page] for i in range(0, len(lines), lines_per_page)]
        num_pages = max(1, len(pages))

        objects = {}

        # Catalog and Pages
        objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        kids = []
        for i in range(num_pages):
            page_id = 3 + (i * 2)
            kids.append(f"{page_id} 0 R")
        kids_str = " ".join(kids).encode("ascii")
        objects[2] = b"<< /Type /Pages /Kids [" + kids_str + b"] /Count " + str(num_pages).encode("ascii") + b" >>"

        # Font object id
        font_id = 3 + (num_pages * 2)

        # Pages and content streams
        for i, page_lines in enumerate(pages):
            page_id = 3 + (i * 2)
            content_id = page_id + 1

            content_lines = [b"BT", b"/F1 11 Tf", b"72 750 Td"]
            for idx, line in enumerate(page_lines):
                if idx > 0:
                    content_lines.append(b"0 -14 Td")
                escaped = self._escape_pdf_text(line)
                content_lines.append(f"({escaped}) Tj".encode("latin-1", "replace"))
            content_lines.append(b"ET")
            stream = b"\n".join(content_lines)
            objects[content_id] = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"

            page_obj = (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Contents " + str(content_id).encode("ascii") + b" 0 R "
                b"/Resources << /Font << /F1 " + str(font_id).encode("ascii") + b" 0 R >> >> >>"
            )
            objects[page_id] = page_obj

        # Font
        objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

        # Build PDF
        output = b"%PDF-1.4\n"
        offsets = {0: 0}
        for obj_id in sorted(objects.keys()):
            offsets[obj_id] = len(output)
            output += f"{obj_id} 0 obj\n".encode("ascii") + objects[obj_id] + b"\nendobj\n"

        max_id = max(objects.keys())
        xref_start = len(output)
        output += f"xref\n0 {max_id + 1}\n".encode("ascii")
        output += b"0000000000 65535 f \n"
        for obj_id in range(1, max_id + 1):
            output += f"{offsets[obj_id]:010d} 00000 n \n".encode("ascii")
        output += b"trailer\n<< /Size " + str(max_id + 1).encode("ascii") + b" /Root 1 0 R >>\nstartxref\n"
        output += f"{xref_start}\n%%EOF\n".encode("ascii")
        return output


# Singleton instance
pdf_exporter = ChatPDFExporter()
