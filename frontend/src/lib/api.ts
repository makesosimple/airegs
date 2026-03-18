const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export interface SourceReference {
  document_title: string;
  source: string;
  doc_type: string;
  chunk_text: string;
  score: number;
}

export interface ChatResponse {
  answer: string;
  sources: SourceReference[];
}

export interface DocumentInfo {
  id: string;
  filename: string;
  title: string;
  source: string;
  doc_type: string;
  date: string | null;
  chunk_count: number;
  status: string;
  created_at: string;
}

export async function sendMessage(
  question: string,
  sourceFilter?: string,
  docTypeFilter?: string
): Promise<ChatResponse> {
  const body: Record<string, string> = { question };
  if (sourceFilter) body.source_filter = sourceFilter;
  if (docTypeFilter) body.doc_type_filter = docTypeFilter;

  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) throw new Error("Soru gönderilemedi.");
  return res.json();
}

export async function uploadDocument(
  file: File,
  source: string,
  docType: string,
  title?: string,
  date?: string
): Promise<DocumentInfo> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("source", source);
  formData.append("doc_type", docType);
  if (title) formData.append("title", title);
  if (date) formData.append("date", date);

  const res = await fetch(`${API_BASE}/api/documents/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) throw new Error("Doküman yüklenemedi.");
  return res.json();
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const res = await fetch(`${API_BASE}/api/documents`);
  if (!res.ok) throw new Error("Dokümanlar listelenemedi.");
  return res.json();
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/documents/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Doküman silinemedi.");
}

export async function getStats(): Promise<{
  name: string;
  points_count: number;
  status: string;
}> {
  const res = await fetch(`${API_BASE}/api/documents/stats`);
  if (!res.ok) throw new Error("İstatistikler alınamadı.");
  return res.json();
}
