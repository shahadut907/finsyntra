/**
 * FinSyntra landing page — all marketing copy and product data in one place.
 *
 * Everything here is grounded in the real product surface:
 *  - 4 ingest formats: PDF, CSV, DOCX, Markdown
 *  - Pipeline: Upload → Parse → Chunk → Embed (ChromaDB) → Retrieve → Generate
 *  - SSE streaming, conversation memory, JWT auth via httpOnly cookies
 *  - 7 RBAC roles, multi-tenant isolation, English + Bangla
 *  - Exports: branded PDF, JSON, Markdown
 * Nothing below invents certifications, customers, or statistics.
 */

export const NAV_LINKS = [
  { label: 'Product', href: '#product' },
  { label: 'Intelligence', href: '#intelligence' },
  { label: 'Capabilities', href: '#capabilities' },
  { label: 'Security', href: '#security' },
  { label: 'Platform', href: '#platform' },
];

export const HERO = {
  eyebrow: 'Retrieval-grounded financial intelligence',
  titleLead: 'Financial intelligence,',
  titleAccent: 'grounded in your data.',
  sub: 'FinSyntra reads your organization’s documents, retrieves the passages that matter, and streams answers it can show its work for — inside a workspace built for tenants, roles, and trust.',
  ctaGuest: 'Explore FinSyntra',
  ctaAuth: 'Enter FinSyntra',
  ctaSecondary: 'See how it works',
  facts: ['Grounded answers, with sources', 'Tenant-isolated workspaces', 'English + বাংলা'],
};

export const WORKSPACE_DOCS = [
  { name: 'Q3 Financial Report.pdf', kind: 'PDF', tone: 'rose', size: '2.4 MB', state: 'Indexed' },
  { name: 'Department Budget.csv', kind: 'CSV', tone: 'aqua', size: '182 KB', state: 'Indexed' },
  { name: 'Expense Analysis.docx', kind: 'DOCX', tone: 'violet', size: '640 KB', state: 'Indexed' },
];

export const DEMO = {
  question: 'Compare Q3 operating expenses with the previous quarter.',
  answer:
    'Operating expenses rose 8.4% quarter over quarter in Q3, driven mainly by logistics and cloud infrastructure. Personnel costs stayed flat, and marketing spend eased after the August campaign freeze. The largest single increase was logistics, up ৳1.2M against Q2.',
  sources: [
    { name: 'Q3 Financial Report.pdf', match: 0.96 },
    { name: 'Department Budget.csv', match: 0.91 },
    { name: 'Expense Analysis.docx', match: 0.87 },
  ],
};

export const PIPELINE_STAGES = [
  {
    key: 'upload',
    label: 'Upload',
    line: 'PDFs, spreadsheets, and notes enter the workspace.',
    tech: 'PDF · CSV · DOCX · Markdown parsing',
  },
  {
    key: 'understand',
    label: 'Understand',
    line: 'Documents are broken into meaning-preserving passages.',
    tech: 'Semantic chunking',
  },
  {
    key: 'embed',
    label: 'Embed',
    line: 'Each passage becomes a searchable vector.',
    tech: 'Embeddings indexed in ChromaDB',
  },
  {
    key: 'retrieve',
    label: 'Retrieve',
    line: 'Every question fetches its most relevant evidence.',
    tech: 'Tenant-scoped vector search',
  },
  {
    key: 'reason',
    label: 'Reason',
    line: 'A local model weighs the evidence in context.',
    tech: 'Ollama · conversation memory',
  },
  {
    key: 'answer',
    label: 'Answer',
    line: 'A grounded response streams back in real time.',
    tech: 'SSE token streaming',
  },
];

export const CAPABILITIES = [
  {
    key: 'grounded',
    title: 'Grounded AI',
    body: 'Answers are assembled from passages retrieved out of your own indexed documents — and FinSyntra shows those sources alongside every response.',
    tag: 'Retrieval-augmented generation',
    featured: true,
  },
  {
    key: 'memory',
    title: 'Conversation memory',
    body: '“What changed since last quarter?” just works. Follow-ups resolve against prior questions, entities, and intent.',
    tag: 'Multi-turn context',
  },
  {
    key: 'streaming',
    title: 'Real-time streaming',
    body: 'Responses arrive token by token over SSE — the interface feels alive, not batch-processed.',
    tag: 'Server-sent events',
  },
  {
    key: 'docs',
    title: 'Document intelligence',
    body: 'Financial reports, budgets, policies, and notes — PDF, CSV, DOCX, and Markdown become one searchable body of knowledge.',
    tag: '4 ingest formats',
  },
  {
    key: 'multilingual',
    title: 'Multilingual by design',
    body: 'Ask in English or বাংলা. Retrieval and reasoning hold up across both.',
    tag: 'EN · বাংলা',
  },
  {
    key: 'exports',
    title: 'Exportable insights',
    body: 'Take an answer with you — as a branded PDF for the board, JSON for systems, or Markdown for notes.',
    tag: 'PDF · JSON · Markdown',
  },
];

export const TENANTS = [
  {
    key: 'A',
    name: 'Tenant A — Northwind Traders',
    docs: ['Q3 Report.pdf', 'Payroll.csv'],
    answer: 'Answers built only from Northwind’s index.',
  },
  {
    key: 'B',
    name: 'Tenant B — Crescent Textiles',
    docs: ['Audit Notes.docx', 'Inventory.csv'],
    answer: 'Crescent’s questions never leave Crescent’s boundary.',
  },
  {
    key: 'C',
    name: 'Tenant C — Arion Logistics',
    docs: ['Fleet Costs.pdf', 'Routes.md'],
    answer: 'Same platform, fully separate knowledge.',
  },
];

export const SECURITY_POINTS = [
  {
    title: 'Tenant isolation',
    body: 'Every retrieval is scoped to the asking tenant. No document is ever globally searchable.',
  },
  {
    title: 'Role-based access',
    body: 'Seven roles — from Employee to Admin — decide which documents a question may draw from.',
  },
  {
    title: 'Authenticated sessions',
    body: 'JWT access in httpOnly cookies with CSRF protection; nothing sensitive lives in the browser’s storage.',
  },
];

export const ROLES = [
  {
    key: 'finance',
    label: 'Finance',
    scope: 'Statements, budgets, expense reports',
    question: 'Compare Q3 operating expenses with the previous quarter.',
    answersFrom: ['Q3 Financial Report.pdf', 'Department Budget.csv'],
  },
  {
    key: 'management',
    label: 'Management',
    scope: 'Departmental summaries, KPIs, status reports',
    question: 'Which departments are over budget this quarter?',
    answersFrom: ['Department Budget.csv', 'Ops Review.docx'],
  },
  {
    key: 'hr',
    label: 'HR',
    scope: 'Policies, leave rules, onboarding material',
    question: 'Summarize our parental leave policy.',
    answersFrom: ['HR Policy Handbook.pdf'],
  },
  {
    key: 'engineering',
    label: 'Engineering',
    scope: 'Specs, architecture docs, incident reports',
    question: 'What changed in the payouts service last sprint?',
    answersFrom: ['Architecture.md', 'Sprint Notes.md'],
  },
  {
    key: 'c_level',
    label: 'C-Level',
    scope: 'Cross-company metrics and board material',
    question: 'Give me a one-paragraph snapshot of this quarter.',
    answersFrom: ['Board Pack.pdf', 'Company KPIs.csv'],
  },
  {
    key: 'admin',
    label: 'Admin',
    scope: 'Users, documents, indexing, audit',
    question: 'Show indexing status across all departments.',
    answersFrom: ['Admin console'],
  },
];

export const MULTILINGUAL = {
  en: {
    label: 'English',
    question: 'Summarize our Q2 revenue performance.',
    answer:
      'Q2 revenue reached ৳4.2 crore, up 12% over Q1. Growth was led by enterprise renewals, while one-time services softened slightly in June.',
  },
  bn: {
    label: 'বাংলা',
    question: 'গত ত্রৈমাসিকের ব্যয়ের প্রধান পরিবর্তনগুলো দেখাও।',
    answer:
      'তৃতীয় প্রান্তিকে মোট ব্যয় আগের প্রান্তিকের তুলনায় ৮.৪% বেড়েছে — প্রধানত লজিস্টিকস ও ক্লাউড ইনফ্রাস্ট্রাকচার খাতে। জনবল ব্যয় স্থির ছিল।',
  },
};

export const ADMIN_TILES = [
  { label: 'Documents indexed', value: '1,284', note: 'across departments', tone: 'mint' },
  { label: 'Active users', value: '96', note: '7 roles assigned', tone: 'blue' },
  { label: 'Queries this week', value: '412', note: 'median 1.9s to first token', tone: 'violet' },
  { label: 'Index queue', value: '0', note: 'all documents current', tone: 'amber' },
];

export const ADMIN_EVENTS = [
  { actor: 'Priya (Finance)', action: 'indexed Q3 Financial Report.pdf', time: '09:41' },
  { actor: 'Rafiq (HR)', action: 'updated leave-policy access', time: '09:18' },
  { actor: 'System', action: 're-embedded 12 passages after edit', time: '08:57' },
  { actor: 'Dana (Admin)', action: 'added user n.hasan@northwind.co', time: '08:32' },
];

export const TECH_STACK = [
  { name: 'React', note: 'workspace UI' },
  { name: 'FastAPI', note: 'API layer' },
  { name: 'RAG', note: 'grounded generation' },
  { name: 'ChromaDB', note: 'vector index' },
  { name: 'Ollama', note: 'local LLM runtime' },
  { name: 'SSE', note: 'token streaming' },
];

export const FINAL_CTA = {
  title: 'Turn organizational knowledge into intelligence.',
  sub: 'Bring your documents. FinSyntra brings the answers — grounded, streamed, and inside your boundaries.',
  primaryGuest: 'Enter FinSyntra',
  primaryAuth: 'Open your workspace',
  secondary: 'Sign in',
};
