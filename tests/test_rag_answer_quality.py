"""RAG answer-quality regressions: chunking, prompt context, citations, scoping.

Root cause these guard against (observed 2026-11-01): text cleanup turned
every blank line into a single newline, so the paragraph chunker could not
split a PDF and indexed it as ONE chunk; the prompt builder then kept only the
first 600 and last 200 characters of any chunk over 800, so every section
after the first never reached the model ("Harbor API targets" was answered
from the environments section, and the availability target was "not found").
All values below are fictional and unrelated to any indexed document.
"""
from unittest.mock import MagicMock

import pytest

from src.backend.utils.document_processor import DocumentProcessor
from src.backend.services.rag_service import RAGService


# ── minimal PDF builder (no PDF writer is installed in the venv) ────────────

def _pdf(pages):
    """pages: list of [(font 'R'|'B', size, x, y, text)] -> PDF bytes."""
    objects = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
               3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"}
    kids, next_id = [], 5
    for lines in pages:
        stream = b"".join(
            b"BT /%s %d Tf %d %d Td (%s) Tj ET\n" % (b"F1" if f == "R" else b"F2", s, x, y, t.encode("latin-1"))
            for f, s, x, y, t in lines)
        content_id, page_id = next_id, next_id + 1
        next_id += 2
        objects[content_id] = b"<< /Length %d >>\nstream\n%sendstream" % (len(stream), stream)
        objects[page_id] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                            b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>" % content_id)
        kids.append(page_id)
    objects[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out, offsets = bytearray(b"%PDF-1.4\n"), {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (oid, objects[oid])
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for oid in sorted(objects):
        out += b"%010d 00000 n \n" % offsets[oid]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def _handbook_pdf():
    footer = lambda n: [("R", 8, 72, 40, "Example evaluation footer | ZX-01"), ("R", 8, 540, 40, str(n))]
    page1 = [
        ("B", 22, 72, 740, "Operations Manual"),
        ("B", 13, 72, 700, "A1. Ownership and environments"),
        ("R", 10, 72, 684, "The platform is called Zephyr Gateway. Its lead is Kim Ortiz. It runs in"),
        ("R", 10, 72, 670, "test and live environments, and live changes need a reviewed record."),
        ("B", 13, 72, 640, "A2. Objectives and incidents"),
        ("R", 10, 72, 624, "Zephyr Gateway targets 98.7% weekly availability and a p90 latency"),
        ("R", 10, 72, 610, "below 333 milliseconds. Sev A must be acknowledged within 7 minutes"),
        ("R", 10, 72, 596, "and updated every 45 minutes. The duty lead owns incident messages."),
    ] + footer(1)
    page2 = [
        ("B", 22, 72, 740, "Operations Manual"),
        ("B", 13, 72, 700, "A3. Backups"),
        ("R", 10, 72, 684, "Backups run every 3 hours and are kept for 21 days."),
    ] + footer(2)
    return _pdf([page1, page2])


@pytest.fixture
def processor():
    p = DocumentProcessor()
    p.chunk_size, p.chunk_overlap = 800, 100
    return p


def test_pdf_sections_become_separate_chunks_with_their_heading(processor, tmp_path):
    path = tmp_path / "ops_manual.pdf"
    path.write_bytes(_handbook_pdf())
    chunks = [c.content for c in processor.process_pdf(str(path))]

    objectives = [c for c in chunks if "98.7% weekly availability" in c]
    assert len(chunks) >= 3, chunks
    assert len(objectives) == 1
    # The heading path travels with the section, and the whole rule is kept.
    assert objectives[0].startswith("Operations Manual > A2. Objectives and incidents")
    assert "within 7 minutes" in objectives[0] and "duty lead owns incident messages" in objectives[0]
    # Section text is not mixed into another section's chunk.
    assert not any("98.7%" in c for c in chunks if "A1. Ownership" in c)


def test_pdf_page_furniture_is_dropped(processor, tmp_path):
    path = tmp_path / "ops_manual.pdf"
    path.write_bytes(_handbook_pdf())
    text = "\n".join(c.content for c in processor.process_pdf(str(path)))
    assert "Example evaluation footer" not in text
    assert "A3. Backups" in text and "21 days" in text


def test_clean_text_keeps_paragraph_breaks(processor):
    cleaned = processor._clean_text("First para line\n  \n\nSecond para\n\n\n\nThird")
    assert cleaned == "First para line\n\nSecond para\n\nThird"


def test_plain_text_numbered_headings_are_kept_with_their_section(processor):
    text = ("Manual\nB1. Scope\nScope text here for the team.\n"
            "B2. Limits and thresholds\nThe limit is 12 units per day for every team.")
    chunks = processor._chunk_sections(processor._mark_plain_headings(text))
    limits = [c for c in chunks if "12 units" in c]
    assert limits and limits[0].startswith("B2. Limits and thresholds")


def test_long_section_split_repeats_heading_and_carries_a_sentence(processor):
    processor.chunk_size = 300
    body = " ".join(f"Rule {i} applies to queue {i} under condition {i}." for i in range(1, 30))
    chunks = processor._chunk_sections(f"# Guide\n\n## R. Queue rules\n\n{body}")
    assert len(chunks) > 1
    assert all(c.startswith("Guide > R. Queue rules\n\n") for c in chunks)
    assert all(len(c) <= 300 + 30 for c in chunks)
    first_tail = chunks[0].rsplit(". ", 1)[-1].rstrip(".")
    assert first_tail.split()[0] in chunks[1]  # last sentence carried over
    assert "Rule 29 applies" in chunks[-1]


def test_markdown_sections_keep_heading_path(processor, tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("# Guide\n\nIntro text that is long enough to keep as a chunk.\n\n"
                    "## Limits\n\nThe daily limit is 12 units for each team member.\n", encoding="utf-8")
    chunks = [c.content for c in processor.process_markdown(str(path))]
    assert any(c.startswith("Guide > Limits") and "12 units" in c for c in chunks)


def test_tiny_section_is_folded_into_the_next(processor):
    text = ("# Manual\n\n## Overview\n\nID: ZX-01 | Effective: 2030\n\n## Q1. Queues\n\n"
            "Queue limit is 12 per team and is reviewed weekly by the queue owner.\n\n"
            "## Q2. Retries\n\nRetries happen 3 times with backoff for every failed job.\n\n"
            "## Q3. Alerts\n\nAlerts page the owner after 4 failures in a row on any queue.")
    chunks = processor._chunk_sections(text)
    assert not any(c.startswith("Manual > Overview") for c in chunks)  # no heading-only chunk
    assert any(c.startswith("Manual > Q1. Queues") and "Overview: ID: ZX-01" in c for c in chunks)
    # Real short sections (with a sentence) stay separate.
    assert any(c.startswith("Manual > Q2. Retries") for c in chunks)
    assert len(chunks) == 3


# ── prompt context ──────────────────────────────────────────────────────────

def _doc(source, similarity, content):
    return {"source": source, "similarity": similarity, "content": content}


def test_context_keeps_whole_section_chunks():
    middle = "MIDDLE-FACT target is 98.7%."
    content = "Heading\n\n" + "a" * 700 + " " + middle + " " + "b" * 300
    [(_, rendered)] = RAGService._context_entries([_doc("x_0123456789abcdef0123456789abcdef.pdf", 0.6, content)])
    assert middle in rendered
    assert rendered.startswith("Document 1 (x.pdf): Heading")


def test_oversized_chunk_is_cut_at_sentence_end_not_in_the_middle():
    sentences = " ".join(f"Sentence {i} states value {i}." for i in range(900))
    [(_, rendered)] = RAGService._context_entries([_doc("big.md", 0.6, sentences)])
    assert rendered.endswith("[... excerpt truncated]")
    assert "Sentence 0 states" in rendered and "Sentence 899" not in rendered
    assert len(rendered) <= RAGService.MAX_CHUNK_CHARS + 80


# ── citations must support the answer ───────────────────────────────────────

SECTION = ("Operations Manual > A2. Objectives and incidents\n\nZephyr Gateway targets 98.7% weekly "
           "availability. Sev A must be acknowledged within 7 minutes. The duty lead owns incident messages.")


def test_not_found_answer_cites_nothing_even_if_retrieved():
    docs = [_doc("ops.pdf", 0.62, SECTION)]
    answer = "I'm not seeing a weekly availability target for Zephyr Gateway in the document."
    assert RAGService._select_citations(docs, answer, "Zephyr Gateway weekly availability target") == []


def test_supported_answer_is_cited_regardless_of_low_similarity():
    docs = [_doc("ops.pdf", 0.21, SECTION)]
    assert RAGService._select_citations(docs, "It targets 98.7% weekly availability.", "uptime?") == ["ops.pdf"]
    assert RAGService._select_citations(
        docs, "The duty lead owns incident messages.", "Who handles incident communication?") == ["ops.pdf"]


def test_partial_answer_with_documented_value_is_cited():
    docs = [_doc("ops.pdf", 0.5, SECTION)]
    answer = "The weekly target is 98.7%; a quarterly target is not specified."
    assert RAGService._select_citations(docs, answer, "quarterly availability?") == ["ops.pdf"]


def test_bangla_answer_with_documented_quantity_cites_the_best_match():
    docs = [_doc("ops.pdf", 0.52, SECTION), _doc("hr.md", 0.31, "Breaks last 7 minutes.")]
    answer = "Sev A ইনসিডেন্ট ৭ মিনিটের মধ্যে স্বীকার করতে হবে।"
    assert RAGService._select_citations(docs, answer, "Sev A কত মিনিটে?") == ["ops.pdf"]


def test_substantive_no_answer_still_cites_the_section_it_restates():
    section = ("Guide > Load test\n\nThe load test processed synthetic invoice events with a failure rate and "
               "latency figures; it does not establish monthly production availability.")
    answer = ("No. The load test covers synthetic invoice events, failure rate and latency, but it does not "
              "establish monthly production availability.")
    assert RAGService._select_citations([_doc("g.pdf", 0.4, section)], answer, "does that prove availability?") == ["g.pdf"]


def test_shared_duration_alone_does_not_cite_unrelated_padding():
    docs = [_doc("ops.pdf", 0.6, SECTION),
            _doc("hr.md", 0.5, "Lunch breaks last 7 minutes longer on Fridays.")]
    cited = RAGService._select_citations(docs, "Sev A acknowledgement is required within 7 minutes.", "Sev A ack?")
    assert cited == ["ops.pdf"]


# ── retrieval scoping ───────────────────────────────────────────────────────

def test_retired_sources_are_excluded_from_vector_query(monkeypatch):
    from src.backend.services import vector_store as vs_mod
    store = object.__new__(vs_mod.VectorStore)
    store.collection = MagicMock()
    store.collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    monkeypatch.setattr(store, "_get_cached_embedding", lambda q: [0.0] * 3, raising=False)
    from src.config.roles import Role
    vs_mod.VectorStore.search_documents(store, "q", Role.ENGINEERING, tenant_id="t1", limit=3,
                                        exclude_sources=["old_v1.pdf"])
    where = store.collection.query.call_args.kwargs["where"]["$and"]
    assert {"tenant_id": {"$eq": "t1"}} in where
    assert {"source": {"$nin": ["old_v1.pdf"]}} in where
    assert any("department" in clause for clause in where)


def test_reindex_indexes_new_chunks_before_removing_stale_ones(tmp_path):
    path = tmp_path / "ops_abc.pdf"
    path.write_bytes(_handbook_pdf())
    rag = object.__new__(RAGService)
    rag.document_processor = DocumentProcessor()
    rag._response_cache = {"k": "v"}
    calls = []
    store = MagicMock()
    store.source_record_ids.return_value = ["t1_ops_abc.pdf_0_legacy00"]
    store.add_documents.side_effect = lambda chunks, tenant_id: calls.append("add") or True
    store.collection.delete.side_effect = lambda ids: calls.append(("delete", ids))
    from src.backend.services.vector_store import VectorStore
    store.chunk_record_id.side_effect = VectorStore.chunk_record_id
    rag.vector_store = store

    result = RAGService.reindex_document(rag, path, "t1", "engineering")
    assert calls[0] == "add" and calls[1] == ("delete", ["t1_ops_abc.pdf_0_legacy00"])
    added = store.add_documents.call_args.args[0]
    assert all(c.metadata["tenant_id"] == "t1" and c.metadata["department"] == "engineering" for c in added)
    assert result["chunks_before"] == 1 and result["chunks_after"] == len(added) >= 3
    assert rag._response_cache == {}


def test_reindex_failure_keeps_previous_index(tmp_path):
    path = tmp_path / "ops_abc.pdf"
    path.write_bytes(_handbook_pdf())
    rag = object.__new__(RAGService)
    rag.document_processor = DocumentProcessor()
    rag._response_cache = {}
    rag.vector_store = MagicMock()
    rag.vector_store.source_record_ids.return_value = ["old"]
    rag.vector_store.add_documents.return_value = False
    with pytest.raises(RuntimeError):
        RAGService.reindex_document(rag, path, "t1", "engineering")
    rag.vector_store.collection.delete.assert_not_called()


# ── multi-part questions, attribution and boundaries (2026-11-02 transcript) ──

def test_enumerated_question_yields_one_query_per_item_bare_and_with_shared_words():
    facets = RAGService._facet_queries(
        "Summarize Zephyr's approved budget, spent amount, readiness review and change freeze together.")
    assert "Summarize Zephyr's change freeze together" in facets
    assert "change freeze" in facets and "readiness review" in facets
    joined = RAGService._facet_queries("Compare the response times for platform incident, payroll request and desk ticket")
    assert "Compare the response times for payroll request" in joined and "desk ticket" in joined
    # one sentence per question when several are asked
    assert RAGService._facet_queries("Why do A and B differ? Is that a calculation error?")[-1] == "Is that a calculation error"
    # single-topic questions are left alone
    assert RAGService._facet_queries("Zephyr gateway targets") == []
    assert RAGService._facet_queries("What is the production database password?") == []


def test_item_answered_by_another_document_reaches_the_context():
    main = [_doc("budget.pdf", 0.72, "Budget section."), _doc("milestones.pdf", 0.70, "Milestones."),
            _doc("scope.pdf", 0.62, "Scope."), _doc("freeze.pdf", 0.30, "A change freeze runs 3-9 May."),
            _doc("noise.pdf", 0.20, "Unrelated.")]
    freeze_hits = [_doc("freeze.pdf", 0.61, "A change freeze runs 3-9 May."), _doc("noise.pdf", 0.25, "Unrelated.")]
    junk_hits = [_doc("noise.pdf", 0.31, "Unrelated.")]  # an item whose best match is below the floor
    merged = RAGService._merge_facet_hits(main, [freeze_hits, junk_hits])
    sources = [d["source"] for d, _ in RAGService._context_entries(merged)]
    assert sources[:3] == ["budget.pdf", "milestones.pdf", "scope.pdf"]
    assert "freeze.pdf" in sources
    assert "noise.pdf" not in sources  # 0.31 < 0.6 x 0.72
    # without facets the context is unchanged (top 3 above the floor)
    assert [d["source"] for d, _ in RAGService._context_entries(main)] == ["budget.pdf", "milestones.pdf", "scope.pdf"]


def test_context_is_capped_even_with_many_items():
    docs = [dict(_doc(f"d{i}.pdf", 0.7 - i * 0.01, "x."), facet_pick=True) for i in range(10)]
    assert len(RAGService._context_entries(docs)) == RAGService.MAX_CONTEXT_DOCS


def test_declared_sources_line_is_removed_and_parsed():
    assert RAGService._split_declared_sources("Answer.\n\nSources: 1, 3") == ("Answer.", [1, 3])
    assert RAGService._split_declared_sources("উত্তর।\n**Sources:** ২ ও ৩") == ("উত্তর।", [2, 3])
    assert RAGService._split_declared_sources("Not stated.\nSources: none") == ("Not stated.", [])
    assert RAGService._split_declared_sources("No line here.") == ("No line here.", None)


def test_declared_sources_are_validated_against_the_prompt():
    docs = [_doc("mkt.pdf", 0.6, "Customer logos require written customer permission plus marketing-lead approval."),
            _doc("hr.pdf", 0.4, "Routine HR requests are acknowledged within 2 business days; exceptions need approval.")]
    answer = "No. Customer logos still require written customer permission and marketing-lead approval."
    # undeclared padding that merely shares generic words is not cited
    assert RAGService._select_citations(docs, answer, "logo approval?", declared=[1]) == ["mkt.pdf"]
    # a number outside the prompt is ignored; an English declaration needs shared evidence
    assert RAGService._select_citations(docs, answer, "logo approval?", declared=[2, 7]) == []
    # A declaration alone is insufficient evidence, including in Bangla.
    bn = [_doc("eng.pdf", 0.5, "The incident commander, not the release manager, owns incident communications.")]
    assert RAGService._select_citations(bn, "ইনসিডেন্ট কমান্ডার যোগাযোগের দায়িত্বে থাকেন।", "কে?", declared=[1]) == []
    # "Sources: none" cites nothing unless a distinctive figure is reproduced
    fig = [_doc("fin.pdf", 0.5, "Approved budget is BDT 612,000.")]
    assert RAGService._select_citations(fig, "Not stated.", "q", declared=[]) == []
    assert RAGService._select_citations(fig, "The budget is BDT 612,000.", "q", declared=[]) == ["fin.pdf"]


def test_comparison_boundaries_are_restored_to_the_documented_strictness():
    evidence = ("p95 latency below 450 milliseconds. Tickets are acknowledged within 4 business hours. "
                "Pause when CPL exceeds BDT 900, each day with at least 10 leads; fewer than 10 leads breaks it.")
    fixed = RAGService._restore_boundaries("p95 ≤ 450 ms; ack ≤ 4 h; CPL ≥ 900; leads ≥ 10; budget > 450", evidence)
    assert fixed == "p95 < 450 ms; ack ≤ 4 h; CPL > 900; leads ≥ 10; budget > 450"
    # numbers absent from the excerpts are never touched
    assert RAGService._restore_boundaries("≤ 37 ms", evidence) == "≤ 37 ms"


class _FacetStore:
    def __init__(self):
        self.calls = []

    def search_documents(self, query, user_role, tenant_id, limit, **kw):
        self.calls.append({"query": query, "role": user_role, "tenant": tenant_id, **kw})
        meta = {"department": "engineering"}
        if query.strip() == "change freeze":
            return [{"source": "eng.md", "similarity": 0.66, "content": "A change freeze runs 3-9 May inclusive.",
                     "metadata": {**meta, "chunk_id": "5"}}]
        return [{"source": "fin.md", "similarity": 0.70, "content": "Zephyr budget is BDT 612,000; spent BDT 200,000.",
                 "metadata": {"department": "finance", "chunk_id": "1"}},
                {"source": "eng.md", "similarity": 0.62, "content": "Zephyr readiness review is due 2 May.",
                 "metadata": {**meta, "chunk_id": "6"}},
                {"source": "gen.md", "similarity": 0.55, "content": "Zephyr is a pilot.",
                 "metadata": {"department": "general", "chunk_id": "2"}}]


def _stub_service(monkeypatch, retired=()):
    from src.backend.services import rag_service as mod
    svc = object.__new__(RAGService)  # NOT the singleton
    svc.vector_store = _FacetStore()
    svc._response_cache = {}
    svc._max_cache_size = 100
    svc._performance_stats = {k: 0 for k in ("cache_hits", "cache_misses", "total_requests", "average_response_time")}
    svc.cuda_available = False
    svc.llm_provider = None
    monkeypatch.setattr(RAGService, "is_ready", lambda self: True)
    monkeypatch.setattr(RAGService, "_retired_sources", staticmethod(lambda tenant: list(retired)))
    monkeypatch.setattr(mod, "can_access_document", lambda role, source: True)
    monkeypatch.setattr(RAGService, "_update_performance_stats", lambda self, t: None)
    return svc


def test_every_item_search_uses_the_same_tenant_and_department_scope(monkeypatch):
    from src.config.roles import Role
    svc = _stub_service(monkeypatch, retired=["old.md"])
    prompts = []

    def fake_generate(self, query, context, *a, **kw):
        prompts.append(context)
        return "Budget BDT 612,000; readiness review 2 May; freeze 3-9 May; latency ≤ 450 ms.\nSources: 1, 2, 3"

    monkeypatch.setattr(RAGService, "_generate_gpu_optimized_response", fake_generate)
    result = svc.process_query(
        query="Summarize Zephyr's budget, readiness review and change freeze.",
        user_id="u", tenant_id="t1", user_role=Role.C_LEVEL)

    calls = svc.vector_store.calls
    assert len(calls) > 1  # main query plus item queries
    assert all(c["tenant"] == "t1" and c["role"] == Role.C_LEVEL and c["exclude_sources"] == ["old.md"] for c in calls)
    assert "change freeze runs 3-9 May" in prompts[0]
    assert result["response"].endswith("latency ≤ 450 ms.")  # Sources line stripped; no evidence for 450
    assert "Sources:" not in result["response"]
    assert set(result["sources"]) == {"fin.md", "eng.md"}


def test_bangla_possessive_suffix_is_not_a_follow_up_pronoun(monkeypatch):
    from src.config.roles import Role
    svc = _stub_service(monkeypatch)
    monkeypatch.setattr(RAGService, "_generate_gpu_optimized_response", lambda self, *a, **kw: "ok\nSources: none")
    history = [{"role": "user", "content": "Tell me about the office"}, {"role": "assistant", "content": "..."}]
    svc.process_query(query="Zephyr-এর launch date কবে?", user_id="u", tenant_id="t1",
                      user_role=Role.C_LEVEL, conversation_history=history)
    assert "Previous topic" not in svc.vector_store.calls[0]["query"]


def test_excerpt_numbers_become_file_names_and_inline_markers_are_declarations():
    sources = ["Ops_0123456789abcdef0123456789abcdef.pdf", "Budget.md"]
    text, declared = RAGService._finalize_answer(
        "Budget is BDT 612,000【2】. Document 1 says the freeze runs 3-9 May (ডকুমেন্ট ১).\nSources: 1", sources)
    assert text == "Budget is BDT 612,000. Ops.pdf says the freeze runs 3-9 May (Ops.pdf)."
    assert declared == [1, 2]
    # numbers outside the prompt are left as written; no declaration stays None
    assert RAGService._finalize_answer("See Document 7.", sources) == ("See Document 7.", None)


def test_inline_file_name_markers_are_removed_and_declared():
    sources = ["Fin_0123456789abcdef0123456789abcdef.pdf", "Mkt.pdf"]
    text, declared = RAGService._finalize_answer("Spend is BDT 360,000 【Fin.pdf】 and differs 【Mkt.pdf】।\nSources: none", sources)
    assert text == "Spend is BDT 360,000 and differs।"
    assert declared == [1, 2]


# ---- 2026-11-02 follow-up: retrieval novelty and claim support -----------
# Different company, categories and figures from the demo corpus on purpose.

_OPEX = ("Finance Report > F2. Operating costs\n\nQ2 operating costs are rent BDT 300,000, utilities BDT 45,000, "
         "travel BDT 80,500 and training BDT 22,000. Total operating costs are BDT 447,500.")
_EVENTS = ("Events Report > V2. September events\n\nTwo trade fairs cost BDT 75,500 in September: venue hire "
           "BDT 40,000 and booth printing BDT 35,500. These costs exclude staff travel.")
_SCOPE = ("Events Report > V8. Scope limits\n\nSeptember event spend is not the same period or cost scope as "
          "the Finance report's Q2 travel cost. Attendee counts are not stated.")
_PLAN = "Events Report > V5. November plan\n\nThe November events budget is BDT 90,000."


def test_item_already_in_context_contributes_its_best_new_section():
    """An item whose top match is a section that only names it (a scope note)
    still brings in the section holding its value."""
    main = [_doc("ev.pdf", 0.65, _SCOPE), _doc("fin.pdf", 0.50, _OPEX), _doc("ev.pdf", 0.49, _PLAN),
            _doc("ev.pdf", 0.37, _EVENTS)]
    hits = [_doc("ev.pdf", 0.59, _SCOPE), _doc("ev.pdf", 0.53, _PLAN), _doc("ev.pdf", 0.49, _EVENTS)]
    merged = RAGService._merge_facet_hits(main, [hits], ["September event spend"])
    contents = [d["content"] for d, _ in RAGService._context_entries(merged)]
    assert _EVENTS in contents
    # without the item text the previous behaviour (top match only) is kept
    plain = RAGService._merge_facet_hits(main, [hits])
    assert _EVENTS not in [d["content"] for d, _ in RAGService._context_entries(plain)]


def test_new_section_must_name_the_item_not_just_score_close():
    main = [_doc("a.pdf", 0.60, "Verification marker policy."), _doc("b.pdf", 0.55, "Other."),
            _doc("c.pdf", 0.50, "More.")]
    hits = [_doc("a.pdf", 0.52, "Verification marker policy."),
            _doc("pad.pdf", 0.50, "Publishing exceptions and approvals for campaign copy.")]
    merged = RAGService._merge_facet_hits(main, [hits], ["what should be verified"])
    assert "pad.pdf" not in [d["source"] for d, _ in RAGService._context_entries(merged)]


def test_listed_category_described_as_containing_its_siblings_is_removed():
    answer = ("Q2 travel cost is BDT 80,500, which includes rent and utilities. "
              "The September events cost BDT 75,500.\n\nSo the two figures differ.")
    fixed, removed = RAGService._remove_unsupported_composition(answer, _OPEX + "\n" + _EVENTS)
    assert removed == ["Q2 travel cost is BDT 80,500, which includes rent and utilities."]
    assert "rent" not in fixed and "BDT 75,500" in fixed and "So the two figures differ." in fixed
    assert fixed.endswith("The documents give no breakdown of travel.")
    # parenthetical form and pronoun form
    for claim in ["Training (rent, utilities and travel) was BDT 22,000.",
                  "Training was BDT 22,000. It covers travel and utilities."]:
        assert RAGService._remove_unsupported_composition(claim, _OPEX)[1], claim


def test_true_negated_or_documented_composition_is_kept():
    evidence = _OPEX + "\n" + _EVENTS
    for answer in [
        "Q2 operating costs include rent (BDT 300,000), utilities, travel and training; the total is BDT 447,500.",
        "Travel (BDT 80,500) does not include rent or utilities, which are listed separately.",
        "Travel (excluding rent and utilities) is BDT 80,500.",
        "The September trade fairs cost BDT 75,500 and exclude staff travel.",
        "Travel is BDT 80,500 and covers the whole quarter.",
    ]:
        assert RAGService._remove_unsupported_composition(answer, evidence) == (answer, []), answer
    stated = (evidence + "\nSales Report > S1. Mix\n\nMedia BDT 50,000, design BDT 20,000, events BDT 30,000. "
              "Events include design work for booths.")
    ok = "Events (BDT 30,000) include design work."
    assert RAGService._remove_unsupported_composition(ok, stated) == (ok, [])


def test_bangla_composition_claim_is_checked_through_its_english_rendering():
    claim = "Travel খরচ (BDT 80,500)-এর মধ্যে rent ও utilities অন্তর্ভুক্ত।"
    answer = "Q2-তে travel খরচ BDT 80,500। " + claim
    docs = [_doc("fin.pdf", 0.6, _OPEX)]
    assert claim in RAGService._claims_to_render(answer, docs, "travel খরচ কত?")
    english = {claim: "Travel cost (BDT 80,500) includes rent and utilities."}
    fixed, removed = RAGService._remove_unsupported_composition(answer, _OPEX, english=english, language="bn")
    assert removed == [claim]
    assert fixed == "Q2-তে travel খরচ BDT 80,500।\n\nনথিতে travel-এর কোনো বিভাজন দেওয়া নেই।"


def test_each_cited_excerpt_must_support_a_claim():
    budget = _doc("proj.pdf", 0.6, "Project Kestrel has spent BDT 360,000 of its BDT 900,000 budget.")
    opex = _doc("fin.pdf", 0.5, "Q3 costs: payroll BDT 1,200,000, cloud BDT 300,000, marketing BDT 360,000.")
    hr = _doc("hr.pdf", 0.4, "HR requests are acknowledged within 2 business days.")
    answer = "Kestrel has spent BDT 360,000 of its budget so far."
    # a figure that also occurs, by coincidence, in another excerpt does not cite it
    assert RAGService._select_citations([budget, opex], answer, "Kestrel spend?", declared=[1]) == ["proj.pdf"]
    # a declared excerpt that supports no sentence is dropped
    assert RAGService._select_citations([budget, opex, hr], answer, "Kestrel spend?", declared=[1, 3]) == ["proj.pdf"]
    # an undeclared figure source is added only when nothing declared supports that claim
    two = answer + " Q3 cloud cost was BDT 300,000."
    assert RAGService._select_citations([budget, opex], two, "q", declared=[1]) == ["proj.pdf", "fin.pdf"]


def test_bangla_claims_without_numbers_are_verified_when_rendered():
    eng = _doc("eng.pdf", 0.5, "The incident commander, not the release manager, owns incident communications.")
    hr = _doc("hr.pdf", 0.4, "Leave requests need manager approval within 5 business days.")
    claim = "ইনসিডেন্টের সময় যোগাযোগের দায়িত্ব ইনসিডেন্ট কমান্ডারের।"
    rendered = {claim: "During an incident, the incident commander is responsible for communications."}
    assert RAGService._claims_to_render(claim, [eng, hr], "দায়িত্ব কার?") == [claim]
    assert RAGService._select_citations([eng, hr], claim, "দায়িত্ব কার?", declared=[1, 2],
                                        english=rendered) == ["eng.pdf"]
    # Without a rendering there is no evidence for either declaration.
    assert RAGService._select_citations([eng, hr], claim, "দায়িত্ব কার?", declared=[1, 2]) == []


def test_claim_rendering_parses_numbered_lines_and_fails_closed():
    svc = object.__new__(RAGService)

    class Provider:
        def __init__(self, reply=None, error=False):
            self.reply, self.error, self.seen = reply, error, None

        def generate(self, prompt, system=None):
            self.seen = (prompt, system)
            if self.error:
                raise RuntimeError("down")
            return self.reply

    svc.llm_provider = Provider("1. First sentence.\n2) Second sentence.\nnoise")
    assert svc._render_claims_in_english(["প্রথম", "দ্বিতীয়"]) == {"প্রথম": "First sentence.",
                                                                "দ্বিতীয়": "Second sentence."}
    assert "1. প্রথম" in svc.llm_provider.seen[0]
    svc.llm_provider = Provider(error=True)
    assert svc._render_claims_in_english(["প্রথম"]) == {}
    assert svc._render_claims_in_english([]) == {}


def test_pipeline_removes_unsupported_composition_and_cites_per_claim(monkeypatch):
    from src.config.roles import Role
    svc = _stub_service(monkeypatch)

    class Store(_FacetStore):
        def search_documents(self, query, user_role, tenant_id, limit, **kw):
            self.calls.append({"query": query, "tenant": tenant_id, "role": user_role, **kw})
            return [{"source": "fin.pdf", "similarity": 0.7, "content": _OPEX,
                     "metadata": {"department": "finance", "chunk_id": "1"}},
                    {"source": "ev.pdf", "similarity": 0.6, "content": _EVENTS,
                     "metadata": {"department": "events", "chunk_id": "1"}},
                    {"source": "hr.pdf", "similarity": 0.5, "content": "HR requests: 2 business days.",
                     "metadata": {"department": "hr", "chunk_id": "1"}}]

    svc.vector_store = Store()
    monkeypatch.setattr(RAGService, "_generate_gpu_optimized_response", lambda self, *a, **kw: (
        "Q2 travel is BDT 80,500 and includes rent and utilities. September trade fairs cost BDT 75,500.\n"
        "Sources: 1, 2, 3"))
    result = svc.process_query(query="Why do Q2 travel and September event costs differ?",
                               user_id="u", tenant_id="t9", user_role=Role.C_LEVEL)
    assert "rent" not in result["response"] and "no breakdown of travel" in result["response"]
    # the travel claim was removed, so Finance supports nothing left; HR never did
    assert result["sources"] == ["ev.pdf"]
    assert all(c["tenant"] == "t9" for c in svc.vector_store.calls)


# ---- Bangla retrieval when the translation call is rate-limited ----------

class _RateLimitedProvider:
    """Fails the first ``failures`` calls with a rate limit, then translates."""

    def __init__(self, failures, retry_after=1):
        self.failures, self.retry_after, self.calls = failures, retry_after, 0

    def generate(self, prompt, system=None):
        from src.backend.services.llm_provider import LLMGenerationError
        self.calls += 1
        if self.calls <= self.failures:
            raise LLMGenerationError("rate_limited", "busy", retry_after_seconds=self.retry_after)
        return "What is Zephyr's budget?"


def test_translation_retries_a_short_rate_limit_once(monkeypatch):
    from src.backend.services import rag_service as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    svc = object.__new__(RAGService)
    svc.llm_provider = _RateLimitedProvider(failures=1, retry_after=2)
    assert svc._english_retrieval_query("Zephyr-এর budget কত?") == "What is Zephyr's budget?"
    assert svc.llm_provider.calls == 2
    # a long wait is not spent inside a chat request
    svc.llm_provider = _RateLimitedProvider(failures=1, retry_after=600)
    assert svc._english_retrieval_query("Zephyr-এর budget কত?") is None
    assert svc.llm_provider.calls == 1


def test_failed_translation_marks_retrieval_degraded_and_qualifies_absence_claims(monkeypatch):
    from src.backend.services import rag_service as mod
    from src.config.roles import Role
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    svc = _stub_service(monkeypatch)
    svc.llm_provider = _RateLimitedProvider(failures=99)
    monkeypatch.setattr(RAGService, "_generate_gpu_optimized_response", lambda self, *a, **kw: (
        "Zephyr-এর launch date নথিতে উল্লেখ নেই।\nSources: none"))
    result = svc.process_query(query="Zephyr-এর launch date কবে?", user_id="u", tenant_id="t1",
                               user_role=Role.C_LEVEL)
    assert result["retrieval_status"] == "degraded"
    assert "অনুবাদ পরিষেবা ব্যস্ত" in result["response"]  # absence is not presented as fact
    assert svc._response_cache == {}  # the next ask searches again
    # an answer that states only documented facts is left as it is
    monkeypatch.setattr(RAGService, "_generate_gpu_optimized_response", lambda self, *a, **kw: (
        "Zephyr budget BDT 612,000।\nSources: 1"))
    ok = svc.process_query(query="Zephyr-এর budget কত?", user_id="u", tenant_id="t1", user_role=Role.C_LEVEL)
    assert ok["retrieval_status"] == "degraded" and "অনুবাদ" not in ok["response"]


def test_degraded_search_with_no_results_does_not_claim_the_documents_lack_it(monkeypatch):
    from src.backend.services import rag_service as mod
    from src.config.roles import Role
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    svc = _stub_service(monkeypatch)
    svc.llm_provider = _RateLimitedProvider(failures=99)
    svc.vector_store.search_documents = lambda **kw: []
    result = svc.process_query(query="Zephyr-এর launch date কবে?", user_id="u", tenant_id="t1",
                               user_role=Role.C_LEVEL)
    assert result["success"] is False and result["retrieval_status"] == "degraded"
    assert "don't have specific information" not in result["response"]
    assert result["sources"] == []


@pytest.mark.parametrize("question,translation,raw,expected,source", [
    (
        "কর্মী হ্যান্ডবুক অনুযায়ী, পূর্ণকালীন কর্মীরা বছরে কত দিনের বার্ষিক ছুটি ও বেতনসহ অসুস্থতার ছুটি পান? বাংলায় উত্তর দিন।",
        "পূর্ণকালীন কর্মীরা বছরে ১০৫ দিনের বার্ষিক ছুটি পান।",
        "বার্ষিক ছুটি ২০ দিন। বেতনসহ অসুস্থতার ছুটি ১০ দিন।",
        ["২০ দিন", "১০ দিন"], "demo_employee_handbook.md",
    ),
    (
        "পূর্ণকালীন কর্মীরা বছরে কত দিনের বার্ষিক ছুটি পান?",
        "Full-time employees receive a yearly annual leave of 20 days.",
        "পূর্ণকালীন কর্মীরা বছরে ২০ দিনের বার্ষিক ছুটি পান। সোশ্যাল অপারেশনস দলের জন্য প্রশ্ন হওয়া উচিত।",
        ["২০ দিনের বার্ষিক ছুটি"], "demo_employee_handbook.md",
    ),
    (
        "বার্ষিক ছুটি নিয়ে কার সঙ্গে যোগাযোগ করব?",
        "Who should I contact about annual leave?",
        "বার্ষিক ছুটি নিয়ে People Operations দলের সঙ্গে যোগাযোগ করুন।",
        ["People Operations"], "demo_employee_handbook.md",
    ),
    (
        "Paid sick leave কত দিনের, আর কোন team ছুটির প্রশ্ন দেখে?",
        "How many days of paid sick leave are allowed and which team handles leave questions?",
        "বেতনসহ অসুস্থতার ছুটি ১০ দিন। ছুটির প্রশ্ন People Operations দল দেখে।",
        ["১০ দিন", "People Operations"], "demo_employee_handbook.md",
    ),
    (
        "Nimbus equipment ফেরত দিতে কত দিন সময় আছে?",
        "What is the Nimbus equipment return deadline?",
        "Nimbus equipment ফেরত দেওয়ার সময়সীমা ৭ দিন।",
        ["৭ দিন"], "nimbus_returns.md",
    ),
])
def test_bangla_answers_grounded_in_authorized_context(
    monkeypatch, isolated_vector_store, question, translation, raw, expected, source
):
    from pathlib import Path
    from src.backend.utils.document_processor import DocumentChunk
    from src.config.roles import Role

    handbook = (Path(__file__).parents[1] / "src/data/demo_corpus/demo_employee_handbook.md").read_text("utf-8")
    documents = [
        ("demo_employee_handbook.md", "general", handbook),
        ("nimbus_returns.md", "general", "Nimbus equipment return deadline is 7 days. Contact Asset Services."),
        ("restricted.md", "finance", "Full-time employees receive 105 days of annual leave. Ask Social Operations."),
    ]
    assert isolated_vector_store.add_documents([
        DocumentChunk(content, {"source": name, "department": department, "chunk_id": name})
        for name, department, content in documents
    ], tenant_id="scoped")
    assert isolated_vector_store.add_documents([
        DocumentChunk("Nimbus equipment return deadline is 44 days.",
                      {"source": "other_tenant.md", "department": "general", "chunk_id": "other"})
    ], tenant_id="different")

    class Provider:
        def generate(self, prompt, system=None):
            if system.startswith("You translate questions"):
                return translation
            if system.startswith("Translate each numbered"):
                lines = []
                for index, line in enumerate(prompt.splitlines(), 1):
                    name = "Social Operations" if "সোশ্যাল" in line else "People Operations"
                    lines.append(f"{index}. Questions about annual leave go to {name} team.")
                return "\n".join(lines)
            assert "105 days" not in prompt and "44 days" not in prompt
            assert "restricted.md" not in prompt and "other_tenant.md" not in prompt
            assert source in prompt
            return raw + f"\n【{source}】"

    svc = _stub_service(monkeypatch)
    svc.vector_store = isolated_vector_store
    svc.llm_provider = Provider()
    result = svc.process_query(question, "visitor", "scoped", user_role=Role.EMPLOYEE)
    assert result["success"], result
    assert all(fact in result["response"] for fact in expected)
    assert "সোশ্যাল" not in result["response"] and "Social Operations" not in result["response"]
    assert result["sources"] == [source]
    other = svc.process_query(question, "visitor", "no-documents", user_role=Role.EMPLOYEE)
    assert not other["sources"]
    assert not any(fact in other["response"] for fact in expected)
