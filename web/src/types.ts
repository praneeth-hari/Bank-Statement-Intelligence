export interface BBox { page: number; x0: number; y0: number; x1: number; y1: number }

export interface FieldJson {
  text: string;
  value: string | null;
  confidence: number;
  needs_review: boolean;
  flags: string[];
  reasons: string[];
  suggestion: string | null;
  suggestion_verified: boolean;
  bbox: BBox | null;
  source: string;
}

export interface PageInfo { page: number; width: number; height: number; image: string }

export interface StatementSummary {
  id: string;
  filename: string;
  status: "processing" | "ready" | "failed";
  error: string | null;
  created: string;
  approved: boolean;
  approved_at: string | null;
  rows?: number;
  to_review?: number;
  reconciles?: boolean;
}

export interface StatementDetail extends StatementSummary {
  pages: PageInfo[];
  header: Record<string, FieldJson | null>;
  transactions: { row: number; fields: Record<string, FieldJson | null> }[];
  issues: Record<string, unknown>[];
  summary: { rows?: number; fields_to_review?: number; chain_breaks?: number; reconciles?: boolean };
  corrections: number;
}

export type GroupId = "chain" | "repaired" | "text" | "prefix" | "header" | "other";

export interface ReviewItem {
  key: string;
  scope: "header" | "row";
  row: number | null;
  field: string;
  text: string;
  value: string | null;
  confidence: number;
  flags: string[];
  reasons: string[];
  suggestion: string | null;
  suggestion_verified: boolean;
  bbox: BBox | null;
  group: GroupId;
}

export interface GroupInfo { id: GroupId; label: string; hint: string; bulk: boolean; count: number }

export interface ReviewResponse { count: number; items: ReviewItem[]; groups: GroupInfo[]; reconciles: boolean }

export type Action = "correct" | "confirm" | "accept_suggestion";

export interface QueryRow {
  statement_id: string; filename: string; row: number; date: string; description: string;
  debit: string | null; credit: string | null; balance: string;
}

export interface QueryResponse {
  question: string;
  answered: boolean;
  reason?: string;
  parser: "rules" | "model" | null;
  statements: string[];
  rows_considered: number;
  rows_skipped: number;
  notes: string[];
  interpretation?: string;
  kind?: "number" | "groups" | "rows" | "none";
  unit?: "INR" | "transactions";
  matched?: number;
  value?: string | null;
  groups?: { key: string; value: string }[];
  rows?: QueryRow[];
}

export interface StatementCounts { total: number; approved: number; awaiting: number; processing: number; failed: number; fields_to_review: number }

export interface Overview {
  has_data: boolean;
  statements: StatementCounts;
  totals: { debit: string; credit: string; transactions: number; debits: number; credits: number };
  by_month: { month: string; debit: string }[];
  by_type: { type: string; debit: string; count: number }[];
  by_category: { category: string; debit: string; count: number }[];
  balances: {
    statement_id: string; filename: string; bank: string | null; period_start: string; period_end: string;
    first_date: string; last_date: string; first_balance: string; last_balance: string; rows: number;
  }[];
  largest_debits: { statement_id: string; filename: string; row: number; date: string; description: string; debit: string }[];
  notes: string[];
}

export interface QualityCondition {
  id: "digital" | "light" | "medium" | "heavy";
  label: string; docs: number | null; rows: number | null;
  fields: number; flagged: number; wrong: number; caught: number; missed: number; missed_by_field: Record<string, number>;
  accuracy: number | null; flag_rate: number | null; error_recall: number | null;
  outcomes: { trusted_right: number; flagged_fine: number; flagged_wrong: number; trusted_wrong: number };
}

export interface Quality {
  available: boolean;
  conditions: QualityCondition[];
  headline: QualityCondition | null;
  names: { id: string; label: string; restored: number; of: number; wrongly_changed: number; controls: number; uses_model: boolean }[];
  questions: { id: string; label: string; correct: number; of: number; wrong: number; refused: number; in_sample: boolean }[];
  extras_source?: string | null;
  threshold: number;
  note: string;
  reviewer: { reviewed: number; flagged_reviewed: number; flagged_actually_wrong: number; unflagged_corrected: number };
}

export interface Health { status: string; ocr_enabled: boolean; auth: boolean; llm: string | null; samples: number }
export interface SamplesResult { loaded: number; statements: { filename: string; id?: string; result: string }[] }

export interface Tx {
  statement_id: string; filename: string; row: number; date: string; description: string; ref: string | null;
  debit: string | null; credit: string | null; balance: string; type: string; category: string;
}
export interface TxPage {
  has_data: boolean; matched: number; limit: number; offset: number; rows: Tx[]; notes: string[];
  totals: { debit: string; credit: string; debits: number; credits: number };
  facets: { statements: { id: string; filename: string }[]; types: string[]; categories: string[] };
}
export interface CategoryRule { id: number; pattern: string; category: string; matches: number }
export interface Categories {
  rules: CategoryRule[];
  suggestions: { pattern: string; category: string; matches: number }[];
  coverage: { total: number; categorised: number };
}
export interface RecurringItem {
  label: string; rail: string | null; direction: "debit" | "credit"; count: number; months: number;
  amount_kind: "same" | "close" | "varies"; low: string; high: string; total: string; day_of_month: number;
  first_date: string; last_date: string; dates: string[];
}
export interface Recurring {
  has_data: boolean; months_covered: number; items: RecurringItem[]; rules: string; note: string; reason?: string;
}
