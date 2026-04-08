import { useState, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import type { Message, UIFrame } from "../store/campaignStore";
import {
  BriefingCard,
  SegmentSelector,
  ProspectPicker,
  VariantGrid,
  ChannelSelector,
  DeploymentConfirm,
  DeliveryStatusCard,
  ABResults,
  CycleSummary,
  ResearchProgress,
  ClarificationPrompt,
  ErrorCard,
  FeedbackPrompt,
  ManualFeedbackInput,
  QuarantineViewer,
} from "./stubs";

// ---------------------------------------------------------------------------
// Reasoning JSON detector & structured types
// ---------------------------------------------------------------------------

interface ParsedReasoning {
  /** The user-facing reply (clarification_question or extracted message) */
  reply: string;
  /** The one-line reasoning from the orchestrator */
  reasoning: string;
  /** The classified intent */
  intent: string | null;
  /** Next routing node */
  nextNode: string | null;
  /** Raw JSON string for fallback display */
  raw: string;
}

/** Known keys that mark orchestrator classification JSON */
const REASONING_KEYS = ["current_intent", "reasoning", "next_node"];

/**
 * Attempt to extract all JSON blobs from a string that may contain
 * multiple concatenated JSON objects (e.g. from token streaming).
 */
function extractJsonBlobs(text: string): object[] {
  const blobs: object[] = [];
  let depth = 0;
  let start = -1;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === "{") {
      if (depth === 0) start = i;
      depth++;
    } else if (text[i] === "}") {
      depth--;
      if (depth === 0 && start !== -1) {
        try {
          blobs.push(JSON.parse(text.slice(start, i + 1)));
        } catch {
          // not valid JSON, skip
        }
        start = -1;
      }
    }
  }
  return blobs;
}

function parseReasoningContent(content: string): ParsedReasoning | null {
  if (!content.includes("current_intent") && !content.includes("reasoning")) {
    return null;
  }

  const blobs = extractJsonBlobs(content);
  if (blobs.length === 0) return null;

  // Merge all blobs — later ones override earlier
  const merged: Record<string, unknown> = {};
  for (const blob of blobs) {
    const rec = blob as Record<string, unknown>;
    // Must have at least one reasoning key
    if (REASONING_KEYS.some((k) => k in rec)) {
      Object.assign(merged, rec);
    }
  }

  if (!merged.reasoning && !merged.current_intent) return null;

  return {
    reply:
      (merged.clarification_question as string) ??
      (merged.message as string) ??
      "",
    reasoning: (merged.reasoning as string) ?? "",
    intent: (merged.current_intent as string) ?? null,
    nextNode: (merged.next_node as string) ?? null,
    raw: JSON.stringify(merged, null, 2),
  };
}

// ---------------------------------------------------------------------------
// CollapsibleReasoning
// ---------------------------------------------------------------------------

function CollapsibleReasoning({ data }: { data: ParsedReasoning }) {
  const [open, setOpen] = useState(false);

  return (
    <div style={{ padding: "4px 0" }} className="animate-fade-in-up">
      <div
        className="surface-card overflow-hidden"
        style={{
          boxShadow: "0 2px 12px rgba(0,0,0,0.2)",
        }}
      >
        {/* Main reply */}
        {data.reply && (
          <div
            className="prose-assistant"
            style={{
              padding: "14px 18px",
              fontSize: "13px",
              lineHeight: "1.65",
              color: "var(--text-primary)",
              borderBottom: "1px solid var(--border-subtle)",
            }}
          >
            <ReactMarkdown>{data.reply}</ReactMarkdown>
          </div>
        )}

        {/* Reasoning toggle */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="reasoning-toggle"
        >
          <div className="flex items-center gap-2">
            <svg
              width="10"
              height="10"
              viewBox="0 0 10 10"
              fill="none"
              style={{
                transform: open ? "rotate(90deg)" : "rotate(0deg)",
                transition: "transform 0.2s ease",
              }}
            >
              <path d="M3 1.5L7 5L3 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="reasoning-toggle-label">Reasoning</span>
          </div>

          <div className="flex items-center gap-2">
            {data.intent && (
              <span className="reasoning-intent-badge">
                {data.intent}
              </span>
            )}
            {data.nextNode && (
              <span className="reasoning-route-badge">
                → {data.nextNode}
              </span>
            )}
          </div>
        </button>

        {/* Collapsible reasoning body */}
        <div
          className="reasoning-body"
          style={{
            maxHeight: open ? "400px" : "0px",
            opacity: open ? 1 : 0,
            overflow: "hidden",
            transition: "max-height 0.3s ease, opacity 0.25s ease",
          }}
        >
          <div style={{ padding: "12px 18px" }}>
            {/* Reasoning line */}
            {data.reasoning && (
              <div className="reasoning-entry">
                <span className="reasoning-label">Thought</span>
                <p className="reasoning-value">{data.reasoning}</p>
              </div>
            )}

            {/* Classification details */}
            <div className="reasoning-grid">
              {data.intent && (
                <div className="reasoning-entry">
                  <span className="reasoning-label">Intent</span>
                  <span className="reasoning-mono">{data.intent}</span>
                </div>
              )}
              {data.nextNode && (
                <div className="reasoning-entry">
                  <span className="reasoning-label">Route</span>
                  <span className="reasoning-mono">{data.nextNode}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// UIComponentDispatcher
// ---------------------------------------------------------------------------

interface DispatcherProps {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

function UIComponentDispatcher({ frame, onAction }: DispatcherProps) {
  const props = { frame, onAction };

  switch (frame.component) {
    case "BriefingCard":
      return <BriefingCard {...props} />;
    case "SegmentSelector":
      return <SegmentSelector {...props} />;
    case "ProspectPicker":
      return <ProspectPicker {...props} />;
    case "VariantGrid":
      return <VariantGrid {...props} />;
    case "ChannelSelector":
      return <ChannelSelector {...props} />;
    case "DeploymentConfirm":
      return <DeploymentConfirm {...props} />;
    case "DeliveryStatusCard":
      return <DeliveryStatusCard {...props} />;
    case "ABResults":
      return <ABResults {...props} />;
    case "CycleSummary":
      return <CycleSummary {...props} />;
    case "ResearchProgress":
      return <ResearchProgress {...props} />;
    case "ClarificationPrompt":
      return <ClarificationPrompt {...props} />;
    case "FeedbackPrompt":
      return <FeedbackPrompt {...props} />;
    case "ManualFeedbackInput":
      return <ManualFeedbackInput {...props} />;
    case "QuarantineViewer":
      return <QuarantineViewer {...props} />;
    case "ErrorCard":
      return <ErrorCard {...props} />;
    default:
      return (
        <pre
          className="overflow-auto"
          style={{
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            padding: "12px",
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          {JSON.stringify(frame, null, 2)}
        </pre>
      );
  }
}

// ---------------------------------------------------------------------------
// MessageRenderer
// ---------------------------------------------------------------------------

interface MessageRendererProps {
  message: Message;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export default function MessageRenderer({ message, onAction }: MessageRendererProps) {
  const isUser = message.role === "user";

  // Detect orchestrator reasoning JSON in assistant messages
  const reasoning = useMemo(() => {
    if (isUser || !message.content) return null;
    return parseReasoningContent(message.content);
  }, [isUser, message.content]);

  if (message.uiComponent) {
    return (
      <div style={{ padding: "8px 0" }} className="animate-fade-in-up">
        <UIComponentDispatcher frame={message.uiComponent} onAction={onAction} />
      </div>
    );
  }

  // Render reasoning JSON as a structured collapsible block
  if (reasoning) {
    return <CollapsibleReasoning data={reasoning} />;
  }

  // Skip empty assistant messages (e.g. leftover from token streaming)
  if (!isUser && !message.content.trim()) return null;

  return (
    <div
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
      style={{
        padding: "4px 0",
        animation: isUser ? "slide-in-right 0.3s ease-out both" : "slide-in-left 0.3s ease-out both",
      }}
    >
      <div
        className={isUser ? "whitespace-pre-wrap" : "prose-assistant"}
        style={{
          maxWidth: isUser ? "75%" : "85%",
          padding: "10px 14px",
          fontSize: "13px",
          lineHeight: "1.6",
          borderRadius: isUser ? "var(--radius-lg) var(--radius-lg) 4px var(--radius-lg)" : "var(--radius-lg) var(--radius-lg) var(--radius-lg) 4px",
          ...(isUser
            ? {
                background: "var(--accent)",
                color: "var(--bg-base)",
                fontWeight: 500,
              }
            : {
                background: "var(--bg-surface-2)",
                color: "var(--text-primary)",
                border: "1px solid var(--border-subtle)",
              }),
        }}
      >
        {isUser ? message.content : <ReactMarkdown>{message.content}</ReactMarkdown>}
      </div>
    </div>
  );
}
