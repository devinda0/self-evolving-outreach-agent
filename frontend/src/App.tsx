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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4"
         style={{ background: "var(--bg-base)" }}>
      {/* Ambient gradient orbs */}
      <div className="pointer-events-none absolute -left-40 -top-40 h-[500px] w-[500px] rounded-full opacity-30"
           style={{ background: "radial-gradient(circle, rgba(0,212,170,0.12) 0%, transparent 70%)" }} />
      <div className="pointer-events-none absolute -bottom-32 -right-32 h-[400px] w-[400px] rounded-full opacity-20"
           style={{ background: "radial-gradient(circle, rgba(77,171,247,0.1) 0%, transparent 70%)" }} />

      <form
        onSubmit={handleSubmit}
        className="animate-fade-in-up relative w-full max-w-lg space-y-6 p-8"
        style={{
          background: "var(--bg-surface-1)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-xl)",
          boxShadow: "0 0 80px rgba(0,212,170,0.04), 0 2px 40px rgba(0,0,0,0.4)",
        }}
      >
        {/* Logo mark */}
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg"
               style={{ background: "var(--accent-glow)", border: "1px solid rgba(0,212,170,0.2)" }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
            </svg>
          </div>
          <div>
            <h1 style={{ fontFamily: "var(--font-display)", fontSize: "20px", fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
              Signal to Action
            </h1>
            <p style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "2px" }}>
              Launch a new campaign intelligence session
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <label className="block">
            <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
              Product name
            </span>
            <input
              required
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder="e.g. Acme Analytics"
              className="mt-1.5 block w-full outline-none placeholder:opacity-30"
              style={{
                background: "var(--bg-surface-2)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-md)",
                padding: "10px 14px",
                fontSize: "14px",
                color: "var(--text-primary)",
                transition: "border-color 0.2s",
              }}
              onFocus={(e) => e.currentTarget.style.borderColor = "var(--accent)"}
              onBlur={(e) => e.currentTarget.style.borderColor = "var(--border-default)"}
            />
          </label>

          <label className="block">
            <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
              Product description
            </span>
            <textarea
              required
              rows={3}
              value={productDescription}
              onChange={(e) => setProductDescription(e.target.value)}
              placeholder="What does it do and who is it for?"
              className="mt-1.5 block w-full resize-none outline-none placeholder:opacity-30"
              style={{
                background: "var(--bg-surface-2)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-md)",
                padding: "10px 14px",
                fontSize: "14px",
                color: "var(--text-primary)",
                transition: "border-color 0.2s",
              }}
              onFocus={(e) => e.currentTarget.style.borderColor = "var(--accent)"}
              onBlur={(e) => e.currentTarget.style.borderColor = "var(--border-default)"}
            />
          </label>

          <label className="block">
            <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
              Target market
            </span>
            <input
              required
              value={targetMarket}
              onChange={(e) => setTargetMarket(e.target.value)}
              placeholder="e.g. Series A SaaS founders in NA"
              className="mt-1.5 block w-full outline-none placeholder:opacity-30"
              style={{
                background: "var(--bg-surface-2)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-md)",
                padding: "10px 14px",
                fontSize: "14px",
                color: "var(--text-primary)",
                transition: "border-color 0.2s",
              }}
              onFocus={(e) => e.currentTarget.style.borderColor = "var(--accent)"}
              onBlur={(e) => e.currentTarget.style.borderColor = "var(--border-default)"}
            />
          </label>
        </div>

        {error && (
          <p className="animate-fade-in" style={{ fontSize: "13px", color: "var(--danger)", padding: "8px 12px", background: "rgba(255,77,106,0.08)", borderRadius: "var(--radius-sm)", border: "1px solid rgba(255,77,106,0.15)" }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="btn-accent w-full justify-center disabled:opacity-40"
          style={{ padding: "12px 20px", fontSize: "13px", borderRadius: "var(--radius-md)" }}
        >
          {loading ? (
            <>
              <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
              Initializing…
            </>
          ) : (
            "Launch Campaign"
          )}
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

  function handleAction(instanceId: string, actionId: string, payload: Record<string, unknown>) {
    // Clarification responses → send as a regular user message
    const responseText = payload.response ?? payload.selected;
    if (responseText) {
      const text = String(responseText);
      useCampaignStore.getState().addUserMessage(text);
      sendMessage(text);
      return;
    }
    useCampaignStore.getState().setPendingAction(true);
    sendUIAction(instanceId, actionId, payload);
  }

  function handleSend(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;

    useCampaignStore.getState().addUserMessage(text);
    sendMessage(text);
    setInput("");
  }

  const statusColor = wsStatus === "connected"
    ? "var(--success)"
    : wsStatus === "connecting"
      ? "var(--warning)"
      : "var(--danger)";

  return (
    <div className="flex h-screen flex-col" style={{ background: "var(--bg-base)" }}>
      {/* Header */}
      <header
        className="flex shrink-0 items-center justify-between px-5 py-3"
        style={{
          background: "var(--bg-surface-1)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-md"
               style={{ background: "var(--accent-glow)", border: "1px solid rgba(0,212,170,0.15)" }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
            </svg>
          </div>
          <span style={{ fontFamily: "var(--font-display)", fontSize: "15px", fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
            Signal to Action
          </span>
        </div>

        <div className="flex items-center gap-3">
          {currentStage && (
            <span
              className="animate-fade-in"
              style={{
                fontSize: "10px",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                color: "var(--accent)",
                background: "var(--accent-glow)",
                padding: "3px 10px",
                borderRadius: "20px",
                border: "1px solid rgba(0,212,170,0.15)",
              }}
            >
              {currentStage}
            </span>
          )}
          <div className="flex items-center gap-1.5" title={wsStatus}>
            <span
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{ background: statusColor, boxShadow: `0 0 6px ${statusColor}` }}
            />
            <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>
              {wsStatus === "connected" ? "Live" : wsStatus === "connecting" ? "Connecting" : "Offline"}
            </span>
          </div>
        </div>
      </header>

      {/* Messages */}
      <div
        className="flex-1 overflow-y-auto px-4 py-5"
        style={{ background: "var(--bg-base)" }}
      >
        <div className="mx-auto max-w-2xl">
          {messages.map((msg) => (
            <MessageRenderer key={msg.id} message={msg} onAction={handleAction} />
          ))}
          {isStreaming && (
            <div className="flex items-center gap-2 py-2" style={{ color: "var(--text-muted)", fontSize: "12px" }}>
              <span className="flex gap-1">
                <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: "var(--accent)", animation: "typing-pulse 1s ease-in-out infinite" }} />
                <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: "var(--accent)", animation: "typing-pulse 1s ease-in-out 0.2s infinite" }} />
                <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: "var(--accent)", animation: "typing-pulse 1s ease-in-out 0.4s infinite" }} />
              </span>
              Thinking…
            </div>
          )}
          <div ref={threadEndRef} />
        </div>
      </div>

      {/* Input bar */}
      <div className="shrink-0" style={{ background: "var(--bg-surface-1)", borderTop: "1px solid var(--border-subtle)" }}>
        <form
          onSubmit={handleSend}
          className="mx-auto flex max-w-2xl items-center gap-2 px-4 py-3"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Describe your campaign goal…"
            className="flex-1 outline-none placeholder:opacity-30"
            style={{
              background: "var(--bg-surface-2)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-md)",
              padding: "10px 14px",
              fontSize: "13px",
              color: "var(--text-primary)",
              transition: "border-color 0.2s",
            }}
            onFocus={(e) => e.currentTarget.style.borderColor = "var(--accent)"}
            onBlur={(e) => e.currentTarget.style.borderColor = "var(--border-default)"}
          />
          <button type="submit" className="btn-accent" style={{ borderRadius: "var(--radius-md)", padding: "10px 18px" }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </form>
      </div>
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
