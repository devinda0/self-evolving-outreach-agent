import { useState, type FormEvent } from "react";
import type { UIFrame } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

interface VariantOption {
  id: string;
  label: string;
}

type EventType = "open" | "click" | "reply" | "bounce";

interface Props {
  frame: UIFrame;
  onAction: (
    instanceId: string,
    actionId: string,
    payload: Record<string, unknown>,
  ) => void;
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

function EditIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
      <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Event type options
// ---------------------------------------------------------------------------

const EVENT_TYPE_OPTIONS: { value: EventType; label: string; color: string }[] =
  [
    { value: "open", label: "Open", color: "var(--signal-audience)" },
    { value: "click", label: "Click", color: "var(--accent)" },
    { value: "reply", label: "Reply", color: "var(--success)" },
    { value: "bounce", label: "Bounce", color: "var(--danger)" },
  ];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ManualFeedbackInput({ frame, onAction: _onAction }: Props) {
  const variants = (frame.props.variants as VariantOption[]) ?? [];
  const sessionId = useCampaignStore((s) => s.sessionId);

  const [variantId, setVariantId] = useState<string>(variants[0]?.id ?? "");
  const [eventType, setEventType] = useState<EventType>("reply");
  const [qualitativeSignal, setQualitativeSignal] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!sessionId) {
      setError("No active session.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/campaign/${sessionId}/feedback/manual`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            variant_id: variantId || null,
            event_type: eventType,
            qualitative_signal: qualitativeSignal.trim() || null,
          }),
        },
      );
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      setSubmitted(true);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to submit feedback.",
      );
    } finally {
      setLoading(false);
    }
  }

  const inputStyle = {
    background: "var(--bg-surface-2)",
    border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-sm)",
    padding: "8px 12px",
    fontSize: "13px",
    color: "var(--text-primary)",
    outline: "none",
    width: "100%",
    transition: "border-color 0.2s",
  } as const;

  const labelStyle = {
    fontSize: "10px",
    fontWeight: 600 as const,
    textTransform: "uppercase" as const,
    letterSpacing: "0.06em",
    color: "var(--text-muted)",
    display: "block" as const,
    marginBottom: "6px",
  };

  if (submitted) {
    return (
      <div
        className="surface-card animate-fade-in-up"
        style={{ boxShadow: "0 2px 16px rgba(0,0,0,0.25)" }}
      >
        <div
          style={{
            borderTop: "2px solid var(--success)",
            padding: "20px",
            display: "flex",
            alignItems: "center",
            gap: "10px",
          }}
        >
          <span
            style={{
              color: "var(--success)",
              display: "flex",
              alignItems: "center",
            }}
          >
            <CheckIcon />
          </span>
          <div>
            <p
              style={{
                fontFamily: "var(--font-display)",
                fontSize: "13px",
                fontWeight: 700,
                color: "var(--text-primary)",
              }}
            >
              Feedback submitted
            </p>
            <p
              style={{
                fontSize: "12px",
                color: "var(--text-muted)",
                marginTop: "2px",
              }}
            >
              Your manual report has been recorded for{" "}
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
                {eventType}
              </span>{" "}
              {variantId ? (
                <>
                  on variant{" "}
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    {variantId.slice(0, 8)}
                  </span>
                </>
              ) : null}
              .
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="surface-card overflow-hidden animate-fade-in-up"
      style={{ boxShadow: "0 2px 16px rgba(0,0,0,0.25)" }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid var(--accent)",
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          gap: "10px",
        }}
      >
        <span style={{ color: "var(--accent)", display: "flex" }}>
          <EditIcon />
        </span>
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "13px",
            fontWeight: 700,
            color: "var(--text-primary)",
            letterSpacing: "-0.01em",
          }}
        >
          Report Manual Feedback
        </span>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} style={{ padding: "16px 20px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          {/* Variant selector */}
          {variants.length > 0 && (
            <label>
              <span style={labelStyle}>Variant</span>
              <select
                value={variantId}
                onChange={(e) => setVariantId(e.target.value)}
                style={inputStyle}
                onFocus={(e) =>
                  (e.currentTarget.style.borderColor = "var(--accent)")
                }
                onBlur={(e) =>
                  (e.currentTarget.style.borderColor = "var(--border-default)")
                }
              >
                <option value="">— All variants —</option>
                {variants.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          {/* Event type */}
          <div>
            <span style={labelStyle}>Engagement event</span>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {EVENT_TYPE_OPTIONS.map((opt) => {
                const active = eventType === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setEventType(opt.value)}
                    style={{
                      padding: "6px 14px",
                      borderRadius: "var(--radius-sm)",
                      fontSize: "12px",
                      fontFamily: "var(--font-mono)",
                      fontWeight: active ? 700 : 400,
                      cursor: "pointer",
                      border: `1px solid ${active ? opt.color : "var(--border-default)"}`,
                      background: active
                        ? `${opt.color}18`
                        : "var(--bg-surface-2)",
                      color: active ? opt.color : "var(--text-secondary)",
                      transition: "all 0.15s",
                    }}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Qualitative signal */}
          <label>
            <span style={labelStyle}>Notes (optional)</span>
            <textarea
              value={qualitativeSignal}
              onChange={(e) => setQualitativeSignal(e.target.value)}
              placeholder="Describe the engagement signal or add context…"
              rows={2}
              style={{ ...inputStyle, resize: "none" }}
              onFocus={(e) =>
                (e.currentTarget.style.borderColor = "var(--accent)")
              }
              onBlur={(e) =>
                (e.currentTarget.style.borderColor = "var(--border-default)")
              }
            />
          </label>

          {/* Error */}
          {error && (
            <p
              className="animate-fade-in"
              style={{
                fontSize: "12px",
                color: "var(--danger)",
                padding: "8px 12px",
                background: "rgba(255,77,106,0.08)",
                borderRadius: "var(--radius-sm)",
                border: "1px solid rgba(255,77,106,0.15)",
              }}
            >
              {error}
            </p>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="btn-accent"
            style={{
              width: "100%",
              justifyContent: "center",
              padding: "10px",
              borderRadius: "var(--radius-sm)",
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? (
              <>
                <span
                  className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
                  style={{ marginRight: "6px" }}
                />
                Submitting…
              </>
            ) : (
              "Submit Feedback"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
