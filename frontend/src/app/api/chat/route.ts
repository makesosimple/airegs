const API_BASE = process.env.API_URL || "http://127.0.0.1:8000";

export async function POST(req: Request) {
  const body = await req.json();

  // Vercel AI SDK sends messages array, extract the last user message
  const messages = body.messages || [];
  const lastMessage = messages[messages.length - 1];
  const question = lastMessage?.content || "";

  // Extract filters from body data if present
  const data = body.data || {};

  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      source_filter: data.source_filter || null,
      doc_type_filter: data.doc_type_filter || null,
    }),
  });

  // Pass through the stream
  return new Response(response.body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "X-Vercel-AI-Data-Stream": "v1",
    },
  });
}
