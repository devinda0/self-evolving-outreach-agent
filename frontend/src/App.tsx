import { useState, useRef, useEffect, type FormEvent } from "react";
import { useCampaignStore } from "./store/campaignStore";
import { useWebSocket } from "./hooks/useWebSocket";
import MessageRenderer from "./components/MessageRenderer";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Session start form
// ---------------------------------------------------------------------------

function SessionForm({ onStart }: { onStart: (id: string) => void }) {
  const [productName, setProductName] = useState("");
  const [productDescription, setProductDescription] = useState("");
  const [targetMarket, setTargetMarket] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/campaign/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_name: productName,
          product_description: productDescription,
          target_market: targetMarket,
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      const data: { session_id: string } = await res.json();
      onStart(data.session_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start session");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md space-y-4 rounded-xl bg-white p-6 shadow-lg"
      >
        <h1 className="text-xl font-bold text-gray-900">Signal to Action</h1>
        <p className="text-sm text-gray-500">Start a new campaign session</p>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Product name</span>
          <input
            required
            value={productName}
            onChange={(e) => setProductName(e.target.value)}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Product description</span>
          <textarea
            required
            rows={3}
            value={productDescription}
            onChange={(e) => setProductDescription(e.target.value)}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Target market</span>
          <input
            required
            value={targetMarket}
            onChange={(e) => setTargetMarket(e.target.value)}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
          />
        </label>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {loading ? "Starting…" : "Start Campaign"}
        </button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chat thread
// ---------------------------------------------------------------------------

function ChatThread() {
  const messages = useCampaignStore((s) => s.messages);
  const sessionId = useCampaignStore((s) => s.sessionId);
  const wsStatus = useCampaignStore((s) => s.wsStatus);
  const currentStage = useCampaignStore((s) => s.currentStage);
  const isStreaming = useCampaignStore((s) => s.isStreaming);

  const { sendMessage, sendUIAction } = useWebSocket(sessionId);

  const [input, setInput] = useState("");
  const threadEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleSend(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;

    useCampaignStore.getState().addUserMessage(text);
    sendMessage(text);
    setInput("");
  }

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3">
        <h1 className="text-lg font-bold text-gray-900">Signal to Action</h1>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {currentStage && (
            <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-indigo-700">
              {currentStage}
            </span>
          )}
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              wsStatus === "connected"
                ? "bg-green-500"
                : wsStatus === "connecting"
                  ? "bg-yellow-400"
                  : "bg-red-500"
            }`}
            title={wsStatus}
          />
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {messages.map((msg) => (
          <MessageRenderer key={msg.id} message={msg} onAction={sendUIAction} />
        ))}
        {isStreaming && (
          <div className="my-1 text-xs text-gray-400">Assistant is typing…</div>
        )}
        <div ref={threadEndRef} />
      </div>

      {/* Input bar */}
      <form
        onSubmit={handleSend}
        className="flex items-center gap-2 border-t border-gray-200 bg-white px-4 py-3"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message…"
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        <button
          type="submit"
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
        >
          Send
        </button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// App root
// ---------------------------------------------------------------------------

export default function App() {
  const sessionId = useCampaignStore((s) => s.sessionId);
  const setSessionId = useCampaignStore((s) => s.setSessionId);

  if (!sessionId) {
    return <SessionForm onStart={setSessionId} />;
  }

  return <ChatThread />;
}
