import { useState } from "react";
import type { UIFrame } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface ClarificationQuestion {
  id: string;
  question: string;
  why_it_matters?: string;
  suggested_options?: string[];
  category?: string;
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

const CATEGORY_COLORS: Record<string, { color: string; bg: string }> = {
  sender_identity: { color: "#74c0fc", bg: "rgba(116,192,252,0.12)" },
  value_prop:      { color: "var(--signal-channel)", bg: "rgba(255,146,43,0.12)" },
  tone:            { color: "#cc5de8", bg: "rgba(204,93,232,0.12)" },
  goal:            { color: "var(--success)", bg: "rgba(81,207,102,0.1)" },
  constraints:     { color: "var(--warning)", bg: "rgba(255,212,59,0.12)" },
  differentiator:  { color: "var(--signal-competitor)", bg: "rgba(255,107,107,0.12)" },
  relationship:    { color: "var(--signal-audience)", bg: "rgba(77,171,247,0.12)" },
  timing:          { color: "#22d3ee", bg: "rgba(34,211,238,0.1)" },
};

function CategoryBadge({ category }: { category: string }) {
  const s = CATEGORY_COLORS[category] ?? { color: "var(--text-muted)", bg: "var(--bg-elevated)" };
  return (
    <span
      style={{
        fontSize: "9px",
        fontWeight: 700,
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: s.color,
        background: s.bg,
        border: `1px solid ${s.color}33`,
        borderRadius: "3px",
        padding: "2px 7px",
      }}
    >
      {category.replace("_", " ")}
    </span>
  );
}

function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 70 ? "var(--success)" : pct >= 40 ? "var(--warning)" : "var(--error)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
      <div
        style={{
          flex: 1,
          height: "4px",
          borderRadius: "2px",
          background: "var(--bg-surface-3)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            borderRadius: "2px",
            background: color,
            transition: "width 0.5s ease",
          }}
        />
      </div>
      <span
        style={{
          fontSize: "10px",
          fontFamily: "var(--font-mono)",
          fontWeight: 600,
          color,
          minWidth: "32px",
          textAlign: "right",
        }}
      >
        {pct}%
      </span>
    </div>
  );
}

export default function ContentClarification({ frame, onAction }: Props) {
  const questions = (frame.props.questions as ClarificationQuestion[]) ?? [];
  const confidenceScore = (frame.props.confidence_score as number) ?? 0;
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [freeText, setFreeText] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const skipAction = frame.actions.find(
    (a) => a.action_type === "content_skip_clarification" || a.id === "content-skip-clarification"
  );

  function handleOptionSelect(questionId: string, option: string) {
    if (submitted) return;
    setAnswers((prev) => ({ ...prev, [questionId]: option }));
    // Clear free text if option is selected
    setFreeText((prev) => {
      const next = { ...prev };
      delete next[questionId];
      return next;
    });
  }

  function handleFreeTextChange(questionId: string, text: string) {
    if (submitted) return;
    setFreeText((prev) => ({ ...prev, [questionId]: text }));
    // Clear option if free text is used
    setAnswers((prev) => {
      const next = { ...prev };
      delete next[questionId];
      return next;
    });
  }

  function getAnswer(questionId: string): string {
    return answers[questionId] || freeText[questionId] || "";
  }

  function handleSubmitAll() {
    if (submitted) return;
    setSubmitted(true);

    // Collect all Q&A pairs and send as one combined response
    const answeredPairs = questions
      .map((q) => {
        const answer = getAnswer(q.id);
        return answer ? `${q.question}: ${answer}` : null;
      })
      .filter(Boolean);

    const combinedResponse = answeredPairs.join("\n");
    if (combinedResponse) {
      // Send as a response payload — the campaign API handles it as a user message
      onAction(frame.instance_id, "content_clarify_submit", {
        response: combinedResponse,
      });
    }
  }

  function handleSkip() {
    if (submitted) return;
    setSubmitted(true);
    if (skipAction) {
      onAction(frame.instance_id, skipAction.id, skipAction.payload);
    } else {
      onAction(frame.instance_id, "content-skip-clarification", {});
    }
  }

  const answeredCount = questions.filter((q) => getAnswer(q.id)).length;

  return (
    <div
      className="surface-card overflow-hidden"
      style={{
        opacity: submitted ? 0.6 : 1,
        transition: "opacity 0.3s",
        boxShadow: "0 0 40px rgba(0,212,170,0.04), 0 4px 24px rgba(0,0,0,0.3)",
      }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid var(--warning)",
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ fontSize: "14px" }}>?</span>
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "13px",
              fontWeight: 700,
              color: "var(--text-primary)",
              letterSpacing: "-0.01em",
            }}
          >
            Content Clarification
          </span>
        </div>
        <span
          style={{
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          {answeredCount}/{questions.length} answered
        </span>
      </div>

      {/* Confidence bar */}
      <div style={{ padding: "10px 20px 6px" }}>
        <div
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
            marginBottom: "6px",
            letterSpacing: "0.05em",
            textTransform: "uppercase",
          }}
        >
          Context confidence
        </div>
        <ConfidenceBar score={confidenceScore} />
      </div>

      {/* Questions */}
      <div style={{ padding: "8px 20px 16px", display: "flex", flexDirection: "column", gap: "16px" }}>
        {questions.map((q) => {
          const selectedOption = answers[q.id];
          const currentFreeText = freeText[q.id] ?? "";
          return (
            <div
              key={q.id}
              style={{
                padding: "12px 14px",
                background: "var(--bg-surface-3)",
                borderRadius: "var(--radius-md)",
                border: `1px solid ${getAnswer(q.id) ? "var(--accent)" : "var(--border-default)"}`,
                transition: "border-color 0.2s",
              }}
            >
              {/* Category + question */}
              <div style={{ display: "flex", alignItems: "flex-start", gap: "8px", marginBottom: "8px" }}>
                {q.category && <CategoryBadge category={q.category} />}
                <p
                  style={{
                    margin: 0,
                    fontSize: "12.5px",
                    lineHeight: "1.6",
                    color: "var(--text-primary)",
                    fontWeight: 500,
                  }}
                >
                  {q.question}
                </p>
              </div>

              {/* Why it matters */}
              {q.why_it_matters && (
                <p
                  style={{
                    margin: "0 0 10px",
                    fontSize: "11px",
                    lineHeight: "1.5",
                    color: "var(--text-muted)",
                    fontStyle: "italic",
                  }}
                >
                  {q.why_it_matters}
                </p>
              )}

              {/* Suggested options */}
              {q.suggested_options && q.suggested_options.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "8px" }}>
                  {q.suggested_options.map((opt) => (
                    <button
                      key={opt}
                      type="button"
                      disabled={submitted || isPendingAction}
                      className="btn-ghost"
                      style={
                        selectedOption === opt
                          ? {
                              borderColor: "var(--accent)",
                              color: "var(--accent)",
                              background: "var(--accent-glow)",
                            }
                          : submitted
                            ? { opacity: 0.4, cursor: "default" }
                            : undefined
                      }
                      onClick={() => handleOptionSelect(q.id, opt)}
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              )}

              {/* Free text input */}
              <input
                type="text"
                placeholder="Or type your own answer…"
                value={currentFreeText}
                disabled={submitted || isPendingAction}
                onChange={(e) => handleFreeTextChange(q.id, e.target.value)}
                style={{
                  width: "100%",
                  padding: "7px 10px",
                  fontSize: "12px",
                  fontFamily: "var(--font-body)",
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border-default)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text-primary)",
                  outline: "none",
                  boxSizing: "border-box",
                }}
              />
            </div>
          );
        })}
      </div>

      {/* Footer actions */}
      <div
        style={{
          padding: "12px 20px",
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          gap: "8px",
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          className="btn-ghost"
          disabled={submitted || isPendingAction}
          onClick={handleSkip}
          style={submitted ? { opacity: 0.4, cursor: "default" } : undefined}
        >
          Skip — generate now
        </button>
        <button
          type="button"
          className="btn-accent"
          disabled={answeredCount === 0 || submitted || isPendingAction}
          onClick={handleSubmitAll}
          style={{
            marginLeft: "auto",
            opacity: answeredCount === 0 || submitted || isPendingAction ? 0.4 : 1,
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          {isPendingAction && submitted ? (
            <>
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
              Generating…
            </>
          ) : (
            `Submit & Generate (${answeredCount}/${questions.length})`
          )}
        </button>
      </div>
    </div>
  );
}
