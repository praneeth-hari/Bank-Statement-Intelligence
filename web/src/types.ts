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

export type GroupId = "chain" | "repaired" | "prefix" | "header" | "other";

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
