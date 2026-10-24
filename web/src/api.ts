import type { Action, QueryResponse, ReviewResponse, StatementDetail, StatementSummary } from "./types";

export const API_BASE: string = import.meta.env.VITE_API_URL ?? "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, init);
  if (!res.ok) {
    let message = res.statusText || `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep the status text */
    }
    throw new ApiError(res.status, message);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  list: () => request<StatementSummary[]>("/statements"),
  get: (id: string) => request<StatementDetail>(`/statements/${id}`),
  review: (id: string) => request<ReviewResponse>(`/statements/${id}/review`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ id: string }>("/statements", { method: "POST", body: form });
  },
  remove: (id: string) => request<void>(`/statements/${id}`, { method: "DELETE" }),
  correct: (id: string, row: number | null, field: string, action: Action, value?: string) =>
    request<{ id: number; remaining_to_review: number; reconciles: boolean }>(
      `/statements/${id}/corrections`, json("POST", { row, field, action, value })),
  confirmGroup: (id: string, group: string) =>
    request<{ confirmed: number; ids: number[]; remaining_to_review: number }>(
      `/statements/${id}/corrections/bulk`, json("POST", { group })),
  undo: (id: string, correctionId: number) =>
    request<{ deleted: number }>(`/statements/${id}/corrections/${correctionId}`, { method: "DELETE" }),
  approve: (id: string) => request<{ approved: boolean }>(`/statements/${id}/approve`, json("POST")),
  reopen: (id: string) => request<{ approved: boolean }>(`/statements/${id}/reopen`, json("POST")),
  ask: (question: string) => request<QueryResponse>("/query", json("POST", { question })),
  imageUrl: (path: string, dpi: number) => `${API_BASE}${path}?dpi=${dpi}`,
  exportUrl: (id: string, fmt: "csv" | "json") => `${API_BASE}/statements/${id}/export.${fmt}`,
};
