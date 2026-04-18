import { useState, useRef, useEffect, type FormEvent } from "react";
import { useCampaignStore } from "./store/campaignStore";
import { useWebSocket } from "./hooks/useWebSocket";
import MessageRenderer from "./components/MessageRenderer";
import MCPServerManager from "./components/MCPServerManager";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CampaignSummary {
  session_id: string;
  product_name: string;
  target_market: string;
  current_intent: string | null;
  cycle_number: number;
  updated_at: string | null;
}

interface RestoredCampaignState {
  content_variants?: Array<Record<string, unknown>>;
  cycle_number?: number;
}

// ---------------------------------------------------------------------------
// Campaign History Panel
// ---------------------------------------------------------------------------

function CampaignHistory({
  onResume,
  onNewCampaign,
}: {
  onResume: (id: string, name: string) => void;
  onNewCampaign: () => void;
}) {
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/campaign/list`);
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const data: CampaignSummary[] = await res.json();
        if (!cancelled) setCampaigns(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  function formatDate(iso: string | null) {
    if (!iso) return "—";
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60_000) return "Just now";
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }

  function stageLabel(intent: string | null): string {
    if (!intent) return "Started";
    const map: Record<string, string> = {
      research: "Researching",
      segment: "Segmentation",
      generate: "Content",
      deploy: "Deployment",
      feedback: "Feedback",
    };
    return map[intent] ?? intent;
  }

  return (
    <div
      className="relative flex min-h-screen items-center justify-center overflow-hidden p-4"
      style={{ background: "var(--bg-base)" }}
    >
      {/* Ambient gradient orbs */}
      <div
        className="pointer-events-none absolute -left-40 -top-40 h-[500px] w-[500px] rounded-full opacity-30"
        style={{ background: "radial-gradient(circle, rgba(0,212,170,0.12) 0%, transparent 70%)" }}
      />
      <div
        className="pointer-events-none absolute -bottom-32 -right-32 h-[400px] w-[400px] rounded-full opacity-20"
        style={{ background: "radial-gradient(circle, rgba(77,171,247,0.1) 0%, transparent 70%)" }}
      />

      <div
        className="animate-fade-in-up relative w-full max-w-2xl p-8"
        style={{
          background: "var(--bg-surface-1)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-xl)",
          boxShadow: "0 0 80px rgba(0,212,170,0.04), 0 2px 40px rgba(0,0,0,0.4)",
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div
              className="flex h-9 w-9 items-center justify-center rounded-lg"
              style={{ background: "var(--accent-glow)", border: "1px solid rgba(0,212,170,0.2)" }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
            <div>
              <h1 style={{ fontFamily: "var(--font-display)", fontSize: "20px", fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
                Signal to Action
              </h1>
              <p style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "2px" }}>
                Resume a campaign or start fresh
              </p>
            </div>
          </div>
          <button
            onClick={onNewCampaign}
            className="btn-accent"
            style={{ padding: "8px 16px", fontSize: "12px", borderRadius: "var(--radius-md)" }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            New Campaign
          </button>
        </div>

        {/* Content */}
        {loading && (
          <div className="flex flex-col items-center gap-3 py-12">
            <div className="campaign-history-loader" />
            <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Loading campaigns…</span>
          </div>
        )}

        {error && (
          <div className="flex flex-col items-center gap-3 py-12">
            <p style={{ fontSize: "13px", color: "var(--danger)" }}>{error}</p>
            <button onClick={onNewCampaign} className="btn-ghost" style={{ fontSize: "12px" }}>
              Start New Instead
            </button>
          </div>
        )}

        {!loading && !error && campaigns.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-12">
            <div
              style={{
                width: "48px",
                height: "48px",
                borderRadius: "var(--radius-lg)",
                background: "var(--bg-surface-2)",
                border: "1px solid var(--border-subtle)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
                <path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" />
              </svg>
            </div>
            <p style={{ fontSize: "13px", color: "var(--text-muted)" }}>No campaigns yet</p>
            <button onClick={onNewCampaign} className="btn-accent" style={{ padding: "10px 24px", fontSize: "13px", borderRadius: "var(--radius-md)" }}>
              Launch Your First Campaign
            </button>
          </div>
        )}

        {!loading && !error && campaigns.length > 0 && (
          <div className="space-y-2" style={{ maxHeight: "400px", overflowY: "auto" }}>
            {campaigns.map((c, i) => (
              <button
                key={c.session_id}
                onClick={() => onResume(c.session_id, c.product_name || "Untitled Campaign")}
                className="campaign-history-item animate-fade-in-up"
                style={{ animationDelay: `${i * 40}ms` }}
              >
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <div className="campaign-history-icon">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0 text-left">
                    <div
                      className="truncate"
                      style={{
                        fontSize: "13px",
                        fontWeight: 600,
                        color: "var(--text-primary)",
                      }}
                    >
                      {c.product_name || "Untitled Campaign"}
                    </div>
                    <div
                      className="truncate"
                      style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}
                    >
                      {c.target_market || "—"}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="campaign-stage-pill">
                    {stageLabel(c.current_intent)}
                  </span>
                  {c.cycle_number > 1 && (
                    <span
                      style={{
                        fontSize: "9px",
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-muted)",
                        background: "var(--bg-surface-3)",
                        padding: "2px 6px",
                        borderRadius: "3px",
                      }}
                    >
                      C{c.cycle_number}
                    </span>
                  )}
                  <span style={{ fontSize: "10px", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                    {formatDate(c.updated_at)}
                  </span>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.5 }}>
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Session start form
// ---------------------------------------------------------------------------

function SessionForm({ onStart, onBack }: { onStart: (id: string, name: string) => void; onBack: () => void }) {
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
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10_000);
      const res = await fetch(`${API_BASE}/campaign/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_name: productName,
          product_description: productDescription,
          target_market: targetMarket,
        }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      const data: { session_id: string } = await res.json();
      onStart(data.session_id, productName);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setError("Request timed out — is the backend running?");
      } else {
        setError(err instanceof Error ? err.message : "Failed to start session");
      }
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
        {/* Back link */}
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1.5 mb-4"
          style={{
            background: "none",
            border: "none",
            fontSize: "11px",
            color: "var(--text-muted)",
            cursor: "pointer",
            padding: 0,
            transition: "color 0.15s",
          }}
          onMouseEnter={(e) => e.currentTarget.style.color = "var(--accent)"}
          onMouseLeave={(e) => e.currentTarget.style.color = "var(--text-muted)"}
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          Back to campaigns
        </button>

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
  const campaignName = useCampaignStore((s) => s.campaignName);
  const wsStatus = useCampaignStore((s) => s.wsStatus);
  const currentStage = useCampaignStore((s) => s.currentStage);
  const isStreaming = useCampaignStore((s) => s.isStreaming);
  const isWaitingForResponse = useCampaignStore((s) => s.isWaitingForResponse);
  const hydrateMessages = useCampaignStore((s) => s.hydrateMessages);
  const resetSession = useCampaignStore((s) => s.resetSession);

  const { sendMessage, sendUIAction } = useWebSocket(sessionId);

  const [input, setInput] = useState("");
  const [showMCP, setShowMCP] = useState(false);
  const threadEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    let cancelled = false;

    async function restoreCampaignPreview() {
      if (!sessionId || messages.length > 0) return;

      try {
        const res = await fetch(`${API_BASE}/campaign/${sessionId}/state`);
        if (!res.ok) return;

        const state = (await res.json()) as RestoredCampaignState;
        const variants = Array.isArray(state.content_variants) ? state.content_variants : [];
        if (!variants.length || cancelled) return;

        hydrateMessages([
          {
            id: `restore-text-${sessionId}`,
            role: "assistant",
            content: `Restored ${variants.length} saved content variant(s) from cycle ${state.cycle_number ?? 1}.`,
            timestamp: new Date(),
          },
          {
            id: `restore-grid-${sessionId}`,
            role: "assistant",
            content: "",
            uiComponent: {
              type: "ui_component",
              component: "VariantGrid",
              instance_id: `restored-variants-${sessionId.slice(0, 8)}`,
              props: { variants },
              actions: [],
            },
            timestamp: new Date(),
          },
        ]);
      } catch {
        // Silent fallback — live chat still works without preload.
      }
    }

    void restoreCampaignPreview();
    return () => {
      cancelled = true;
    };
  }, [hydrateMessages, messages.length, sessionId]);

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
    useCampaignStore.getState().setWaitingForResponse(true);
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
        className="relative flex shrink-0 items-center justify-between px-5 py-3"
        style={{
          background: "var(--bg-surface-1)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div className="flex items-center gap-2.5">
          <button
            onClick={resetSession}
            className="flex h-7 w-7 items-center justify-center rounded-md"
            title="Back to campaigns"
            style={{
              background: "var(--bg-surface-2)",
              border: "1px solid var(--border-default)",
              cursor: "pointer",
              transition: "border-color 0.2s, background 0.2s",
              color: "var(--text-secondary)",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = "var(--accent)";
              e.currentTarget.style.color = "var(--accent)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = "var(--border-default)";
              e.currentTarget.style.color = "var(--text-secondary)";
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
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

        {campaignName && (
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 truncate max-w-[200px] md:max-w-[400px]">
            <span style={{ fontSize: "14px", fontWeight: 600, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
              {campaignName}
            </span>
          </div>
        )}

        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowMCP(true)}
            className="flex h-7 w-7 items-center justify-center rounded-md"
            title="MCP Server Settings"
            style={{
              background: "var(--bg-surface-2)",
              border: "1px solid var(--border-default)",
              cursor: "pointer",
              transition: "border-color 0.2s, color 0.2s",
              color: "var(--text-muted)",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = "var(--accent)";
              e.currentTarget.style.color = "var(--accent)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = "var(--border-default)";
              e.currentTarget.style.color = "var(--text-muted)";
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
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

      {/* MCP Server Manager Modal */}
      {showMCP && <MCPServerManager onClose={() => setShowMCP(false)} />}

      {/* Messages */}
      <div
        className="flex-1 overflow-y-auto px-4 py-5"
        style={{ background: "var(--bg-base)" }}
      >
        <div className="mx-auto max-w-2xl md:max-w-3xl lg:max-w-4xl">
          {messages.map((msg) => (
            <MessageRenderer key={msg.id} message={msg} onAction={handleAction} />
          ))}

          {/* Thinking indicator — shown when waiting for first response after user sends message */}
          {isWaitingForResponse && !isStreaming && (
            <div className="thinking-indicator animate-fade-in-up">
              <div className="thinking-indicator-inner">
                <div className="thinking-orb-container">
                  <div className="thinking-orb" />
                  <div className="thinking-orb thinking-orb-2" />
                  <div className="thinking-orb thinking-orb-3" />
                </div>
                <div className="thinking-text-container">
                  <span className="thinking-label">Processing</span>
                  <span className="thinking-dots">
                    <span className="thinking-dot" />
                    <span className="thinking-dot" style={{ animationDelay: "0.2s" }} />
                    <span className="thinking-dot" style={{ animationDelay: "0.4s" }} />
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Streaming indicator */}
          {isStreaming && (
            <div className="flex items-center gap-2 py-2" style={{ color: "var(--text-muted)", fontSize: "12px" }}>
              <span className="flex gap-1">
                <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: "var(--accent)", animation: "typing-pulse 1s ease-in-out infinite" }} />
                <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: "var(--accent)", animation: "typing-pulse 1s ease-in-out 0.2s infinite" }} />
                <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: "var(--accent)", animation: "typing-pulse 1s ease-in-out 0.4s infinite" }} />
              </span>
              Streaming…
            </div>
          )}
          <div ref={threadEndRef} />
        </div>
      </div>

      {/* Input bar */}
      <div className="shrink-0" style={{ background: "var(--bg-surface-1)", borderTop: "1px solid var(--border-subtle)" }}>
        <form
          onSubmit={handleSend}
          className="mx-auto flex max-w-2xl md:max-w-3xl lg:max-w-4xl items-center gap-2 px-4 py-3"
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
  const setCampaignName = useCampaignStore((s) => s.setCampaignName);
  const [view, setView] = useState<"history" | "new">("history");

  // If session is active, show chat
  if (sessionId) {
    return <ChatThread />;
  }

  // New campaign form
  if (view === "new") {
    return <SessionForm 
      onStart={(id, name) => { 
        setCampaignName(name); 
        setSessionId(id); 
      }} 
      onBack={() => setView("history")} 
    />;
  }

  // Default: show history
  return (
    <CampaignHistory
      onResume={(id, name) => { 
        setCampaignName(name); 
        setSessionId(id); 
      }}
      onNewCampaign={() => setView("new")}
    />
  );
}
