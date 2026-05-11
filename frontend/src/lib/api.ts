import type { QueryResponse } from "@/types/chat";

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ||
  "";

export const apiBaseUrl = BASE_URL;

async function parseJson(res: Response): Promise<QueryResponse> {
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return (await res.json()) as QueryResponse;
}

export async function queryCorpus(params: {
  message: string;
  sessionId?: string;
  topK?: number;
}): Promise<QueryResponse> {
  const res = await fetch(`${BASE_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: params.message,
      top_k: params.topK ?? 4,
      session_id: params.sessionId,
    }),
  });
  return parseJson(res);
}

export async function queryPdf(params: {
  message: string;
  sessionId?: string;
  file?: File | null;
}): Promise<QueryResponse> {
  const fd = new FormData();
  fd.append("message", params.message);
  if (params.sessionId) fd.append("session_id", params.sessionId);
  if (params.file) fd.append("file", params.file);
  const res = await fetch(`${BASE_URL}/query_pdf`, { method: "POST", body: fd });
  return parseJson(res);
}

export async function queryImage(params: {
  message: string;
  sessionId?: string;
  file?: File | null;
}): Promise<QueryResponse> {
  const fd = new FormData();
  fd.append("message", params.message);
  if (params.sessionId) fd.append("session_id", params.sessionId);
  if (params.file) fd.append("file", params.file);
  const res = await fetch(`${BASE_URL}/query_image`, { method: "POST", body: fd });
  return parseJson(res);
}
