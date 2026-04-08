import type { UIFrame, UIAction } from "../store/campaignStore";

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

function CycleIcon() {
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
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
    </svg>
  );
}

function TrophyIcon() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 9H4.5a2.5 2.5 0 010-5H6" />
      <path d="M18 9h1.5a2.5 2.5 0 000-5H18" />
      <path d="M4 22h16" />
      <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" />
      <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" />
      <path d="M18 2H6v7a6 6 0 0012 0V2z" />
    </svg>
  );
}

function SearchIcon() {
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
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Learning delta renderer — renders plain text with metric lines highlighted
// ---------------------------------------------------------------------------

function LearningDelta({ text }: { text: string }) {
  return (
    <div
      style={{
        fontFamily: "var(--font-body)",
        fontSize: "12px",
        lineHeight: "1.75",
        color: "var(--text-secondary)",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {text.split("\n").map((line, i) => {
        const isMetricLine =
          line.includes("open_rate=") ||
          line.includes("reply_rate=") ||
          line.includes("Winner:") ||
          line.includes("No winner");

        if (line.startsWith("Engagement summary:") || line.startsWith("Winner:")) {
          return (
            <div
              key={i}
              style={{
                fontSize: "10px",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
                color: "var(--text-muted)",
                marginTop: i > 0 ? "10px" : "0",
                marginBottom: "4px",
              }}
            >
              {line}
            </div>
          );
        }

        if (isMetricLine) {
          return (
            <div
              key={i}
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "11px",
                color: "var(--text-primary)",
                padding: "3px 8px",
                marginBottom: "2px",
                background: "var(--bg-surface-3)",
                borderRadius: "4px",
                borderLeft: "2px solid var(--accent-dim)",
              }}
            >
              {line.trim()}
            </div>
          );
        }

        return (
          <span key={i}>
            {line}
            {"\n"}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CycleSummary({ frame, onAction }: Props) {
  const cycleNumber = (frame.props.cycle_number as number) ?? 0;
  const learningDelta = (frame.props.learning_delta as string) ?? "";
  const winnerVariantId = (frame.props.winner_variant_id as string | null) ?? null;
  const winnerReplyRate = (frame.props.winner_reply_rate as number | null) ?? null;

  const nextCycleAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "run_next_cycle" || a.id === "run-next-cycle",
  );
  const viewFindingsAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "view_findings" || a.id === "view-findings",
  );

  function handleNextCycle() {
    if (nextCycleAction) {
      onAction(frame.instance_id, nextCycleAction.id, {
        ...nextCycleAction.payload,
        action: "run_next_cycle",
      });
    } else {
      onAction(frame.instance_id, "run_next_cycle", { action: "run_next_cycle" });
    }
  }

  function handleViewFindings() {
    if (viewFindingsAction) {
      onAction(frame.instance_id, viewFindingsAction.id, {
        ...viewFindingsAction.payload,
        action: "view_findings",
      });
    } else {
      onAction(frame.instance_id, "view_findings", { action: "view_findings" });
    }
  }

  const hasWinner = winnerVariantId !== null;
  const winnerPct =
    winnerReplyRate != null ? Math.round(winnerReplyRate * 100) : null;

  return (
    <div
      className="surface-card overflow-hidden animate-fade-in-up"
      style={{
        boxShadow: "0 0 40px rgba(0,212,170,0.04), 0 4px 24px rgba(0,0,0,0.3)",
      }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid var(--accent)",
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ color: "var(--accent)" }}>
            <CycleIcon />
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
            Cycle {cycleNumber} Complete
          </span>
        </div>
        <span
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            color: "var(--accent)",
            background: "var(--accent-glow)",
            border: "1px solid rgba(0,212,170,0.2)",
            borderRadius: "4px",
            padding: "2px 8px",
          }}
        >
          loop closed
        </span>
      </div>

      {/* Winner callout */}
      {hasWinner && (
        <div
          style={{
            margin: "16px 20px 0",
            padding: "12px 16px",
            background:
              "linear-gradient(135deg, rgba(0,212,170,0.1) 0%, rgba(0,212,170,0.04) 100%)",
            border: "1px solid rgba(0,212,170,0.3)",
            borderRadius: "var(--radius-sm)",
            display: "flex",
            alignItems: "center",
            gap: "12px",
          }}
        >
          <span style={{ color: "var(--accent)", flexShrink: 0 }}>
            <TrophyIcon />
          </span>
          <div>
            <div
              style={{
                fontSize: "11px",
                fontWeight: 700,
                color: "var(--accent)",
                fontFamily: "var(--font-mono)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: "2px",
              }}
            >
              Winning Variant
            </div>
            <div
              style={{
                fontSize: "12px",
                color: "var(--text-primary)",
                fontFamily: "var(--font-body)",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  color: "var(--text-secondary)",
                }}
              >
                {winnerVariantId}
              </span>
              {winnerPct !== null && (
                <span
                  style={{
                    marginLeft: "10px",
                    fontFamily: "var(--font-mono)",
                    fontSize: "12px",
                    fontWeight: 700,
                    color: "var(--accent)",
                  }}
                >
                  {winnerPct}% reply rate
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* No-winner notice */}
      {!hasWinner && (
        <div
          style={{
            margin: "16px 20px 0",
            padding: "10px 14px",
            background: "rgba(255,178,36,0.07)",
            border: "1px solid rgba(255,178,36,0.2)",
            borderRadius: "var(--radius-sm)",
            fontSize: "11px",
            lineHeight: "1.5",
            color: "var(--warning)",
            fontFamily: "var(--font-body)",
          }}
        >
          No winner declared — insufficient sample size this cycle. Consider
          running longer before the next cycle.
        </div>
      )}

      {/* Learning delta */}
      {learningDelta && (
        <div
          style={{
            margin: "14px 20px 0",
            padding: "14px 16px",
            background: "var(--bg-surface-3)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          <div
            style={{
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginBottom: "10px",
            }}
          >
            Learning Delta
          </div>
          <LearningDelta text={learningDelta} />
        </div>
      )}

      {/* Actions */}
      <div
        style={{
          padding: "16px 20px",
          borderTop: "1px solid var(--border-subtle)",
          marginTop: "16px",
          display: "flex",
          gap: "8px",
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          className="btn-accent"
          onClick={handleNextCycle}
        >
          Run Next Cycle
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={handleViewFindings}
        >
          <SearchIcon />
          View Updated Findings
        </button>
      </div>
    </div>
  );
}
