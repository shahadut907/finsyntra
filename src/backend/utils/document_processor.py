"""
Document Processing System for FinSyntra RAG Chatbot
Handles markdown, CSV, and other document formats
"""
import os
import pandas as pd
from typing import List, Dict, Any
from pathlib import Path
import re
import shutil
from src.config.settings import settings
from src.config.roles import DOCUMENT_CATEGORIES, Department
import io
import logging
import warnings


class DocumentChunk:
    """Represents a chunk of processed document"""
    def __init__(self, content: str, metadata: Dict[str, Any]):
        self.content = content
        self.metadata = metadata
        
    def __repr__(self):
        return f"DocumentChunk(length={len(self.content)}, source={self.metadata.get('source', 'unknown')})"


logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Processes various document formats for RAG system"""
    
    def __init__(self):
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        
    def process_markdown(self, file_path: str) -> List[DocumentChunk]:
        """Process markdown files into chunks"""
        logger.info(f"📄 Processing markdown: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
            
            # Get document metadata
            filename = os.path.basename(file_path)
            doc_meta = DOCUMENT_CATEGORIES.get(filename, {
                "department": Department.GENERAL,
                "type": "unknown"
            })
            
            # One chunk per heading section, each carrying its heading path, so
            # a split section is still attributable to its topic.
            chunks = self._chunk_sections(content.replace("\r\n", "\n"))
            
            # The length floor drops header-only fragments produced by splitting;
            # it must not discard a whole short document, which would otherwise
            # be rejected as having no indexable content.
            if content.strip() and not any(len(c.strip()) > 50 for c in chunks):
                chunks = [content.strip()]

            # Create DocumentChunk objects
            document_chunks = []
            for i, chunk in enumerate(chunks):
                if len(chunk.strip()) > 50 or len(chunks) == 1:  # Only keep substantial chunks
                    metadata = {
                        "source": filename,
                        "chunk_id": i,
                        "department": doc_meta.get("department"),
                        "doc_type": doc_meta.get("type"),
                        "content_type": "markdown"
                    }
                    document_chunks.append(DocumentChunk(chunk, metadata))
            
            logger.info(f"[+] Created {len(document_chunks)} chunks from {filename}")
            return document_chunks
            
        except Exception as e:
            logger.error(f"[-] Error processing {file_path}: {e}")
            return []
    
    def process_csv(self, file_path: str) -> List[DocumentChunk]:
        """Process CSV files into searchable chunks"""
        logger.info(f"[*] Processing CSV: {file_path}")
        
        try:
            df = pd.read_csv(file_path)
            filename = os.path.basename(file_path)
            
            # Get document metadata
            doc_meta = DOCUMENT_CATEGORIES.get(filename, {
                "department": Department.GENERAL,
                "type": "data"
            })
            
            chunks = []
            
            # Create summary chunk
            summary = self._create_csv_summary(df, filename)
            summary_metadata = {
                "source": filename,
                "chunk_id": 0,
                "department": doc_meta.get("department"),
                "doc_type": "data_summary",
                "content_type": "csv_summary"
            }
            chunks.append(DocumentChunk(summary, summary_metadata))
            
            # Create chunks for groups of rows (if dataset is large)
            if len(df) > 20:  # For large datasets, group rows
                chunk_size = 10  # Rows per chunk
                for i in range(0, len(df), chunk_size):
                    chunk_df = df.iloc[i:i+chunk_size]
                    chunk_content = self._format_csv_chunk(chunk_df, i, filename)
                    
                    metadata = {
                        "source": filename,
                        "chunk_id": i // chunk_size + 1,
                        "department": doc_meta.get("department"),
                        "doc_type": "data_rows",
                        "content_type": "csv_data",
                        "row_range": f"{i}-{min(i+chunk_size-1, len(df)-1)}"
                    }
                    chunks.append(DocumentChunk(chunk_content, metadata))
            else:
                # For small datasets, include all data in one chunk
                all_data = self._format_csv_chunk(df, 0, filename)
                metadata = {
                    "source": filename,
                    "chunk_id": 1,
                    "department": doc_meta.get("department"),
                    "doc_type": "data_complete",
                    "content_type": "csv_data"
                }
                chunks.append(DocumentChunk(all_data, metadata))
            
            logger.info(f"[+] Created {len(chunks)} chunks from {filename}")
            return chunks
            
        except Exception as e:
            logger.error(f"[-] Error processing {file_path}: {e}")
            return []
    
    def process_pdf(self, file_path: str) -> List[DocumentChunk]:
        """Process PDF files into chunks, with OCR fallback for scanned pages"""
        logger.info(f"📑 Processing PDF: {file_path}")

        filename = os.path.basename(file_path)
        doc_meta = DOCUMENT_CATEGORIES.get(filename, {
            "department": Department.GENERAL,
            "type": "report"
        })

        try:
            # Layout-aware extraction keeps each heading with its section and
            # drops repeated page furniture. Without it, the plain-text
            # extractors yield single newlines only, which the paragraph
            # chunker could not split: a whole PDF became one chunk, and the
            # prompt builder then kept only its first 600 characters.
            structured = self._extract_pdf_structured(file_path)
            if structured.strip():
                chunks = self._chunk_sections(structured)
            else:
                raw_text = self._extract_pdf_text(file_path)
                if not raw_text.strip():
                    logger.warning(f"[!] No extractable text found in {filename}")
                    return []
                cleaned_text = self._clean_text(raw_text)
                chunks = self._chunk_sections(self._mark_plain_headings(cleaned_text))

            document_chunks = []
            for i, chunk in enumerate(chunks):
                if len(chunk.strip()) < 10:
                    continue  # Skip trivial chunks
                metadata = {
                    "source": filename,
                    "chunk_id": i,
                    "department": doc_meta.get("department"),
                    "doc_type": doc_meta.get("type"),
                    "content_type": "pdf"
                }
                document_chunks.append(DocumentChunk(chunk, metadata))

            logger.info(f"[+] Created {len(document_chunks)} chunks from {filename}")
            return document_chunks

        except Exception as e:
            logger.error(f"[-] Error processing {file_path}: {e}")
            return []

    # ----------------- PDF Helper Methods ----------------- #
    _BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demibold", re.I)
    _PAGE_NUMBER_LINE = re.compile(r"^(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?$", re.I)

    def _extract_pdf_structured(self, file_path: str) -> str:
        """Text with ``#`` headings and blank-line paragraphs, from font layout.

        Generic rules only: the body size is the size most characters use;
        a short line set larger than the body, or wholly in a bold face, is a
        heading (larger sizes rank higher). Lines repeated on several pages
        (running headers/footers, digits ignored) are kept once, and page
        numbers are dropped. Returns "" when the layout cannot be read, so the
        caller falls back to the plain-text extractors.
        """
        try:
            from pdfminer.high_level import extract_pages  # type: ignore
            from pdfminer.layout import LTTextContainer, LTTextLine, LTChar  # type: ignore
        except Exception:
            return ""
        from collections import Counter

        lines = []  # (page, text, size, bold, top, bottom)
        margin_lines = set()  # (page, text) inside the top/bottom 10% of the page
        try:
            for page_no, layout in enumerate(extract_pages(file_path)):
                height = float(getattr(layout, "height", 0) or 0)
                for element in layout:
                    if not isinstance(element, LTTextContainer):
                        continue
                    for line in element:
                        if not isinstance(line, LTTextLine):
                            continue
                        chars = [c for c in line if isinstance(c, LTChar) and c.get_text().strip()]
                        text = re.sub(r"\s+", " ", line.get_text()).strip()
                        if not chars or not text:
                            continue
                        sizes = sorted(round(c.size * 2) / 2 for c in chars)
                        bold = sum(1 for c in chars if self._BOLD_FONT.search(c.fontname or "")) > 0.8 * len(chars)
                        lines.append((page_no, text, sizes[len(sizes) // 2], bold, line.y1, line.y0))
                        if height and (line.y0 > 0.9 * height or line.y1 < 0.1 * height):
                            margin_lines.add((page_no, text))
        except Exception as exc:
            logger.warning(f"[!] Layout extraction failed for {file_path}: {exc}")
            return ""
        if not lines:
            return ""

        weight = Counter()
        for _, text, size, _, _, _ in lines:
            weight[size] += len(text)
        body = weight.most_common(1)[0][0]

        # Running headers/footers: the exact same line in the top or bottom
        # margin of more than one page. Exact text only - normalising digits
        # made distinct body lines ("Line 3 ...", "Line 7 ...") look repeated.
        seen_on = {}
        for page_no, text in margin_lines:
            seen_on.setdefault(text.lower(), set()).add(page_no)
        repeated = {k for k, v in seen_on.items() if len(v) > 1}

        def is_heading(text, size, bold):
            if len(text) > 120 or text.endswith((",", ";")):
                return False
            return size >= body + 1.5 or (bold and size >= body - 0.25)

        heading_sizes = sorted({s for _, t, s, b, _, _ in lines if is_heading(t, s, b) and s >= body + 1.5}, reverse=True)

        def level(size):
            if size in heading_sizes:
                return min(heading_sizes.index(size) + 1, 4)
            return min(len(heading_sizes) + 1, 4)

        out, paragraph, emitted = [], [], set()
        prev = None  # (page, bottom, size)

        def flush():
            if paragraph:
                out.append(" ".join(paragraph))
                paragraph.clear()

        for page_no, text, size, bold, top, bottom in lines:
            key = text.lower()
            if self._PAGE_NUMBER_LINE.match(text):
                continue
            if key in repeated and (page_no, text) in margin_lines:
                # Running header/footer: small print is noise everywhere;
                # anything else (a title, an ID line) is kept the first time.
                if size < body or key in emitted:
                    continue
                emitted.add(key)
            if is_heading(text, size, bold):
                flush()
                out.append("#" * level(size) + " " + text)
                prev = None
                continue
            gap_break = (
                prev is None or prev[0] != page_no or (prev[1] - top) > 0.8 * body or abs(prev[2] - size) > 0.5
            )
            if gap_break:
                flush()
            paragraph.append(text)
            prev = (page_no, bottom, size)
        flush()
        return "\n\n".join(out)

    _PLAIN_HEADING = re.compile(
        r"^(?:(?:[A-Z]{1,3}\d+|\d+)(?:\.\d+)*\.?|[IVX]{1,5}\.|(?:section|chapter|part)\s+\w+[.:]?)\s+[A-Z][^.!?]{2,90}$",
        re.I,
    )

    def _mark_plain_headings(self, text: str) -> str:
        """Mark numbered heading lines ("E2. Title", "3.1 Title", "Section 4 Title")
        in layout-free text, so the section chunker can keep them with their body."""
        marked = []
        for line in text.split("\n"):
            stripped = line.strip()
            if self._PLAIN_HEADING.match(stripped) and not stripped.startswith("#"):
                marked.extend(["", "## " + stripped, ""])
            else:
                marked.append(line)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(marked)).strip()

    _MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
    _SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")

    def _chunk_sections(self, text: str) -> List[str]:
        """One chunk per heading section, each prefixed with its heading path.

        A section that fits (with 25% slack, so a rule is not split for a few
        characters) stays whole. Longer sections are split at paragraph, then
        sentence boundaries; every piece repeats the heading path and carries
        the previous piece's last sentence, so a rule split across chunks is
        still understandable on its own. Text before the first heading is its
        own section.
        """
        sections = []  # (path, body)
        stack: List[tuple] = []
        body: List[str] = []

        def close():
            content = "\n\n".join(p for p in body if p.strip()).strip()
            if content:
                sections.append((" > ".join(h for _, h in stack), content))
            body.clear()

        for block in re.split(r"\n\s*\n", text):
            block = block.strip()
            if not block:
                continue
            head_lines, rest = [], []
            for line in block.split("\n"):
                m = self._MD_HEADING.match(line.strip())
                if m and not rest:
                    head_lines.append((len(m.group(1)), m.group(2).strip()))
                else:
                    rest.append(line)
            for lvl, title in head_lines:
                close()
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                stack.append((lvl, title))
            if rest:
                body.append("\n".join(rest).strip())
        close()

        # A section with almost no body (a subtitle over an ID line) makes a
        # chunk that is little more than its heading; it matches broad
        # questions and invites guessing from the title. Fold it into the
        # next section as a labelled paragraph instead.
        merged = []
        carry = ""
        for index, (path, content) in enumerate(sections):
            if carry:
                content = f"{carry}\n\n{content}"
                carry = ""
            # "Tiny" = a fragment without a single complete sentence (an ID or
            # date line under a subtitle); real short rules stay separate.
            tiny = len(content) < self.TINY_SECTION_CHARS and not re.search(r"[.!?।](\s|$)", content)
            if tiny and index + 1 < len(sections):
                label = path.split(" > ")[-1] if path else ""
                carry = f"{label}: {content}" if label else content
                continue
            merged.append((path, content))
        sections = merged

        limit = self.chunk_size
        chunks: List[str] = []
        for path, content in sections:
            prefix = f"{path}\n\n" if path else ""
            if len(prefix) + len(content) <= int(limit * 1.25):
                chunks.append(prefix + content)
                continue
            budget = max(200, limit - len(prefix))
            units: List[tuple] = []  # (text, starts a paragraph)
            for para in content.split("\n\n"):
                if len(para) <= budget:
                    units.append((para, True))
                else:
                    sentences = [s for s in self._SENTENCE_END.split(para) if s.strip()]
                    units.extend((s, i == 0) for i, s in enumerate(sentences))
            pieces, current = [], ""
            for unit, new_para in units:
                while len(unit) > budget:  # a single run-on "sentence"
                    cut = unit.rfind(" ", 0, budget)
                    cut = cut if cut > budget // 2 else budget
                    if current:
                        pieces.append(current)
                        current = ""
                    pieces.append(unit[:cut].strip())
                    unit = unit[cut:].strip()
                if not unit:
                    continue
                if current and len(current) + 2 + len(unit) > budget:
                    pieces.append(current)
                    # Carry the last sentence over so the next piece keeps the
                    # rule it continues.
                    tail = self._SENTENCE_END.split(current)[-1]
                    current = f"{tail} {unit}" if len(tail) <= self.chunk_overlap * 2 else unit
                elif current:
                    current += ("\n\n" if new_para else " ") + unit
                else:
                    current = unit
            if current:
                pieces.append(current)
            chunks.extend(prefix + piece for piece in pieces if piece.strip())
        # No separate outline/table-of-contents chunk: measured, it outranked
        # the answering section for misspelled questions and still led the
        # model to describe sections from their titles.
        return chunks

    TINY_SECTION_CHARS = 160

    def _extract_pdf_text(self, file_path: str) -> str:
        """Extract text from PDF using PyMuPDF or pdfminer; OCR fallback for scanned pages."""
        text_pages: List[str] = []

        # Attempt PyMuPDF first (fast & accurate)
        try:
            import fitz  # type: ignore
            with fitz.open(file_path) as doc:
                for page in doc:
                    page_text = page.get_text("text")
                    if page_text:
                        text_pages.append(page_text)
            if text_pages:
                return "\n".join(text_pages)
        except Exception:
            pass  # Gracefully fall back

        # Attempt pdfminer.six as a secondary option
        try:
            from pdfminer.high_level import extract_pages  # type: ignore
            from pdfminer.layout import LTTextContainer  # type: ignore

            for page_layout in extract_pages(file_path):
                page_txt = ""
                for element in page_layout:
                    if isinstance(element, LTTextContainer):
                        page_txt += element.get_text()
                if page_txt:
                    text_pages.append(page_txt)
            if text_pages:
                return "\n".join(text_pages)
        except Exception:
            pass  # Gracefully fall back

        # Attempt pdfplumber as another fallback (good for tricky PDFs)
        try:
            import pdfplumber  # type: ignore
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    if page_text:
                        text_pages.append(page_text)
            if text_pages:
                return "\n".join(text_pages)
        except Exception:
            pass

        # Attempt PDFium (pypdfium2, already required by pdfplumber). Replaces the
        # former PyPDF2 fallback: PyPDF2 is end-of-life and its content-stream
        # infinite loop (GHSA-4vvm-4w3v-6mr8) is only fixed in pypdf.
        try:
            import pypdfium2 as pdfium  # type: ignore
            pdf = pdfium.PdfDocument(file_path)
            try:
                for index in range(len(pdf)):
                    textpage = pdf[index].get_textpage()
                    page_text = textpage.get_text_bounded() or ""
                    if page_text.strip():
                        text_pages.append(page_text)
            finally:
                pdf.close()
            if text_pages:
                return "\n".join(text_pages)
        except Exception:
            pass

        # Don't rasterize uploads when the host cannot recognize the result.
        if not (shutil.which("pdfinfo") and shutil.which("pdftoppm")):
            return ""
        try:
            from pdf2image import convert_from_path  # type: ignore
            import pytesseract  # type: ignore

            if not shutil.which(pytesseract.pytesseract.tesseract_cmd):
                return ""
            images = convert_from_path(file_path, dpi=300)
            for img in images:
                page_text = pytesseract.image_to_string(img)
                if page_text:
                    text_pages.append(page_text)
            return "\n".join(text_pages)
        except Exception as e:
            logger.warning(f"[!] OCR fallback failed for {file_path}: {e}")

        # If all methods fail, return empty string
        return ""

    def _clean_text(self, text: str) -> str:
        """Clean extracted text by removing non-printable characters and normalising whitespace."""
        # Remove non-printable characters
        cleaned = re.sub(r'[^\x09\x0A\x0D\x20-\x7E\u00A0-\uD7FF\uE000-\uFFFD]', '', text)
        # Consolidate whitespace but keep paragraph breaks: the former
        # "\s+\n" / "\n\s+" rules also turned every blank line into a single
        # newline, leaving the paragraph chunker nothing to split on.
        cleaned = re.sub(r'[ \t\f\v]+', ' ', cleaned)
        cleaned = re.sub(r' *\n *', '\n', cleaned)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    def _chunk_text(self, text: str) -> List[str]:
        """Chunk plain text into manageable pieces following the configured chunk size."""
        paragraphs = text.split('\n\n')
        chunks: List[str] = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) > self.chunk_size and current:
                chunks.append(current.strip())
                current = para
            else:
                current += ("\n\n" + para) if current else para

        if current.strip():
            chunks.append(current.strip())

        # Further split overly large chunks using existing helper
        final_chunks: List[str] = []
        for chunk in chunks:
            if len(chunk) <= self.chunk_size:
                final_chunks.append(chunk)
            else:
                final_chunks.extend(self._split_large_chunk(chunk))

        return final_chunks
    
    def _smart_chunk_markdown(self, content: str) -> List[str]:
        """Smart chunking that respects markdown structure"""
        # Split by headers first
        sections = re.split(r'\n(?=#{1,6}\s)', content)
        
        chunks = []
        current_chunk = ""
        
        for section in sections:
            # If adding this section would exceed chunk size
            if len(current_chunk) + len(section) > self.chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = section
            else:
                current_chunk += "\n" + section if current_chunk else section
        
        # Add the last chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        # If any chunk is still too large, split it further
        final_chunks = []
        for chunk in chunks:
            if len(chunk) <= self.chunk_size:
                final_chunks.append(chunk)
            else:
                # Split large chunks by paragraphs or sentences
                sub_chunks = self._split_large_chunk(chunk)
                final_chunks.extend(sub_chunks)
        
        return final_chunks
    
    def _split_large_chunk(self, text: str) -> List[str]:
        """Split large chunks by paragraphs or sentences"""
        # Try splitting by paragraphs first
        paragraphs = text.split('\n\n')
        
        chunks = []
        current = ""
        
        for para in paragraphs:
            if len(current) + len(para) > self.chunk_size and current:
                chunks.append(current.strip())
                current = para
            else:
                current += "\n\n" + para if current else para
        
        if current.strip():
            chunks.append(current.strip())
        
        return chunks
    
    def _create_csv_summary(self, df: pd.DataFrame, filename: str) -> str:
        """Create a summary of CSV data for better searchability"""
        summary_parts = [
            f"Dataset: {filename}",
            f"Total Records: {len(df)}",
            f"Columns: {', '.join(df.columns.tolist())}",
            ""
        ]
        
        # Add column statistics
        for col in df.columns:
            if df[col].dtype in ['int64', 'float64']:
                summary_parts.append(f"{col}: min={df[col].min()}, max={df[col].max()}, avg={df[col].mean():.2f}")
            elif df[col].dtype == 'object':
                unique_count = df[col].nunique()
                summary_parts.append(f"{col}: {unique_count} unique values")
                if unique_count <= 10:
                    unique_vals = df[col].value_counts().head(5)
                    summary_parts.append(f"  Top values: {dict(unique_vals)}")
        
        return "\n".join(summary_parts)
    
    def _format_csv_chunk(self, df: pd.DataFrame, start_idx: int, filename: str) -> str:
        """Format CSV chunk for better readability"""
        lines = [f"Data from {filename} (rows {start_idx} to {start_idx + len(df) - 1}):"]
        lines.append("")
        
        for idx, row in df.iterrows():
            row_lines = [f"Record {idx}:"]
            for col, val in row.items():
                row_lines.append(f"  {col}: {val}")
            lines.append("\n".join(row_lines))
            lines.append("")
        
        return "\n".join(lines)
    
    def process_directory(self, directory_path: str) -> List[DocumentChunk]:
        """Process all documents in a directory"""
        logger.info(f"[*] Processing directory: {directory_path}")
        
        all_chunks = []
        directory = Path(directory_path)
        
        if not directory.exists():
            logger.error(f"[-] Directory not found: {directory_path}")
            return []
        
        # Process markdown files
        for md_file in directory.glob("*.md"):
            chunks = self.process_markdown(str(md_file))
            all_chunks.extend(chunks)
        
        # Process CSV files
        for csv_file in directory.glob("*.csv"):
            chunks = self.process_csv(str(csv_file))
            all_chunks.extend(chunks)
        
        # Process PDF files
        for pdf_file in directory.glob("*.pdf"):
            chunks = self.process_pdf(str(pdf_file))
            all_chunks.extend(chunks)
        
        logger.info(f"🎉 Total chunks created: {len(all_chunks)}")
        return all_chunks


# Test the processor
if __name__ == "__main__":
    print("🧪 Testing Document Processor")
    print("=" * 40)
    
    processor = DocumentProcessor()
    
    # Create sample test file
    test_dir = "src/data/raw"
    os.makedirs(test_dir, exist_ok=True)
    
    # Create a test markdown file
    test_content = """# Test Document
    
## Introduction
This is a test document for the FinSyntra RAG system.

## Section 1
Here we discuss various company policies and procedures.

### Subsection 1.1
Detailed information about leave policies.

## Section 2
Financial information and budgets.
"""
    
    test_file = os.path.join(test_dir, "test_doc.md")
    with open(test_file, 'w') as f:
        f.write(test_content)
    
    # Test processing
    chunks = processor.process_markdown(test_file)
    
    print(f"\n[*] Test Results:")
    print(f"Created {len(chunks)} chunks")
    
    for i, chunk in enumerate(chunks):
        print(f"\nChunk {i + 1}:")
        print(f"  Length: {len(chunk.content)} chars")
        print(f"  Metadata: {chunk.metadata}")
        print(f"  Content preview: {chunk.content[:100]}...")
    
    # Clean up
    os.remove(test_file)
    print(f"\n[+] Document processor test completed!")
