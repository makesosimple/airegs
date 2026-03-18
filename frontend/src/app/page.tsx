"use client";

import { Thread } from "@/components/thread";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useChatRuntime } from "@assistant-ui/react-ai-sdk";
import Link from "next/link";
import { Settings } from "lucide-react";

export default function ChatPage() {
  const runtime = useChatRuntime();

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-screen">
        {/* Sidebar */}
        <aside className="flex w-56 flex-col border-r bg-sidebar">
          <div className="border-b p-3">
            <h2 className="text-sm font-semibold">AI Regülasyon Asistanı</h2>
          </div>
          <div className="flex-1" />
          <div className="border-t p-3">
            <Link
              href="/admin"
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-accent"
            >
              <Settings size={14} />
              Doküman Yönetimi
            </Link>
          </div>
        </aside>

        {/* Main chat */}
        <div className="flex-1">
          <Thread />
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
}
