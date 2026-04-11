import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface VariantResult {
  variant_id: string;
  sent: number;
  opens: number;
  clicks: number;
  replies: number;
  bounces: number;
  open_rate: number;
  click_rate: number;
  reply_rate: number;
  bounce_rate: number;
}

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

function TrophyIcon() {
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
      <path d="M6 9H4.5a2.5 2.5 0 010-5H6" />
      <path d="M18 9h1.5a2.5 2.5 0 000-5H18" />
      <path d="M4 22h16" />
      <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" />
      <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" />
      <path d="M18 2H6v7a6 6 0 0012 0V2z" />
    </svg>
  );
}

function BarChartIcon() {
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
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Metric bar
// ---------------------------------------------------------------------------

function MetricBar({
  label,
  rate,
  count,
  color,
}: {
  label: string;
  rate: number;
  count: number;
  color: string;
}) {
  const pct = Math.min(100, Math.round(rate * 100));
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "5px",
        }}
      >
        <span
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.05em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
          }}
        >
          {label}
        </span>
        <div style={{ display: "flex", alignItems: "baseline", gap: "4px" }}>
          <span
            style={{
              fontSize: "13px",
              fontFamily: "var(--font-mono)",
              fontWeight: 700,
              color,
            }}
          >
            {pct}%
          </span>
          <span
            style={{
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
            }}
          >
            ({count})
          </span>
        </div>
      </div>
      <div
        style={{
          height: "4px",
          borderRadius: "2px",
          background: "var(--bg-surface-3)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: "2px",
            background: color,
            transition: "width 0.6s ease",
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Variant card
// ---------------------------------------------------------------------------

function VariantCard({
  result,
  isWinner,
  index,
}: {
  result: VariantResult;
  isWinner: boolean;
  index: number;
}) {
  const label =
    index === 0 ? "A" : index === 1 ? "B" : index === 2 ? "C" : `${index + 1}`;

  const accentColor = isWinner ? "var(--accent)" : "var(--text-secondary)";
  const borderColor = isWinner
    ? "rgba(0,212,170,0.3)"
    : "var(--border-subtle)";

  return (
    <div
      className="animate-fade-in-up"
      style={{
        background: isWinner
          ? "linear-gradient(135deg, rgba(0,212,170,0.06) 0%, var(--bg-surface-2) 60%)"
          : "var(--bg-surface-2)",
        border: `1px solid ${borderColor}`,
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        boxShadow: isWinner ? "0 0 24px rgba(0,212,170,0.08)" : "none",
      }}
    >
      {/* Card header */}
      <div
        style={{
          borderTop: `2px solid ${accentColor}`,
          padding: "12px 16px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div
            style={{
              width: "28px",
              height: "28px",
              borderRadius: "6px",
              background: isWinner ? "var(--accent-glow-strong)" : "var(--bg-surface-3)",
              border: `1px solid ${borderColor}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--font-display)",
              fontSize: "13px",
              fontWeight: 800,
              color: accentColor,
            }}
          >
            {label}
          </div>
          <div>
            <div
              style={{
                fontSize: "11px",
                fontFamily: "var(--font-mono)",
                color: "var(--text-muted)",
                letterSpacing: "0.04em",
              }}
            >
              Variant {label}
            </div>
            <div
              style={{
                fontSize: "10px",
                fontFamily: "var(--font-mono)",
                color: "var(--text-muted)",
                marginTop: "1px",
              }}
            >
              {result.variant_id.length > 16
                ? `${result.variant_id.slice(0, 8)}…${result.variant_id.slice(-6)}`
                : result.variant_id}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {isWinner && (
            <span
              style={{
                display: "flex",
                alignItems: "center",
                gap: "4px",
                fontSize: "10px",
                fontFamily: "var(--font-mono)",
                fontWeight: 700,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                color: "var(--accent)",
                background: "var(--accent-glow)",
                border: "1px solid rgba(0,212,170,0.25)",
                borderRadius: "4px",
                padding: "3px 8px",
              }}
            >
              <TrophyIcon />
              Winner
            </span>
          )}
          <span
            style={{
              fontSize: "11px",
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
            }}
          >
            n={result.sent}
          </span>
        </div>
      </div>

      {/* Metrics */}
      <div style={{ padding: "14px 16px" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "12px",
          }}
        >
          <MetricBar
            label="Reply"
            rate={result.reply_rate}
            count={result.replies}
            color={isWinner ? "var(--accent)" : "var(--signal-channel)"}
          />
          <MetricBar
            label="Open"
            rate={result.open_rate}
            count={result.opens}
            color="var(--signal-audience)"
          />
          <MetricBar
            label="Click"
            rate={result.click_rate}
            count={result.clicks}
            color="var(--signal-market)"
          />
          <MetricBar
            label="Bounce"
            rate={result.bounce_rate}
            count={result.bounces}
            color="var(--signal-competitor)"
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ABResults({ frame, onAction }: Props) {
  const results = (frame.props.results as VariantResult[]) ?? [];
  const winnerVariantId = (frame.props.winner_variant_id as string | null) ?? null;
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);
  const significance = frame.props.significance as {
    comparisons?: Array<{
      variant_a: string;
      variant_b: string;
      metric: string;
      rate_a: number;
      rate_b: number;
      chi_squared: number;
      significant: boolean;
      effect_size: number;
    }>;
    winner_id?: string | null;
    is_significant?: boolean;
    recommendation?: string;
  } | null;

  const nextCycleAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "run_next_cycle" || a.id === "run-next-cycle",
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

  const hasWinner = winnerVariantId !== null;

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
          borderTop: "2px solid var(--signal-channel)",
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ color: "var(--signal-channel)" }}>
            <BarChartIcon />
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
            A/B Results
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span
            style={{
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
            }}
          >
            {results.length} variant{results.length !== 1 ? "s" : ""}
          </span>
          {hasWinner ? (
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
              winner declared
            </span>
          ) : (
            <span
              style={{
                fontSize: "10px",
                fontFamily: "var(--font-mono)",
                color: "var(--text-muted)",
                background: "var(--bg-surface-3)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
            >
              no winner yet
            </span>
          )}
        </div>
      </div>

      {/* No-data state */}
      {results.length === 0 && (
        <div
          style={{
            padding: "32px 20px",
            textAlign: "center",
            color: "var(--text-muted)",
            fontSize: "13px",
            fontFamily: "var(--font-body)",
          }}
        >
          No engagement data available yet.
        </div>
      )}

      {/* Variant cards */}
      {results.length > 0 && (
        <div
          style={{
            padding: "16px 20px",
            display: "flex",
            flexDirection: "column",
            gap: "12px",
          }}
        >
          {results.map((result, i) => (
            <VariantCard
              key={result.variant_id}
              result={result}
              isWinner={result.variant_id === winnerVariantId}
              index={i}
            />
          ))}
        </div>
      )}

      {/* Statistical significance panel */}
      {significance && significance.comparisons && significance.comparisons.length > 0 && (
        <div
          style={{
            margin: "0 20px 12px",
            padding: "14px",
            background: significance.is_significant
              ? "rgba(0,212,170,0.05)"
              : "var(--bg-surface-3)",
            border: `1px solid ${significance.is_significant ? "rgba(0,212,170,0.2)" : "var(--border-subtle)"}`,
            borderRadius: "var(--radius-sm)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              marginBottom: "8px",
            }}
          >
            <span
              style={{
                fontSize: "10px",
                fontFamily: "var(--font-mono)",
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: significance.is_significant ? "var(--accent)" : "var(--text-muted)",
              }}
            >
              Statistical Significance (chi-squared, p &lt; 0.05)
            </span>
            <span
              style={{
                fontSize: "9px",
                fontFamily: "var(--font-mono)",
                padding: "1px 6px",
                borderRadius: "3px",
                background: significance.is_significant
                  ? "var(--accent-glow)"
                  : "var(--bg-elevated)",
                color: significance.is_significant ? "var(--accent)" : "var(--text-muted)",
                border: `1px solid ${significance.is_significant ? "rgba(0,212,170,0.2)" : "var(--border-subtle)"}`,
              }}
            >
              {significance.is_significant ? "SIGNIFICANT" : "NOT YET"}
            </span>
          </div>
          {significance.comparisons.map((comp, idx) => (
            <div
              key={idx}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "4px 0",
                fontSize: "11px",
                fontFamily: "var(--font-mono)",
                color: "var(--text-secondary)",
                borderBottom:
                  idx < (significance.comparisons?.length ?? 0) - 1
                    ? "1px solid var(--border-subtle)"
                    : "none",
              }}
            >
              <span>
                {comp.variant_a.slice(0, 8)} vs {comp.variant_b.slice(0, 8)}
              </span>
              <span style={{ display: "flex", gap: "12px" }}>
                <span>chi²={comp.chi_squared.toFixed(3)}</span>
                <span>Δ={Math.round(comp.effect_size * 100)}%</span>
                <span
                  style={{
                    color: comp.significant ? "var(--accent)" : "var(--text-muted)",
                    fontWeight: comp.significant ? 700 : 400,
                  }}
                >
                  {comp.significant ? "✓ sig" : "—"}
                </span>
              </span>
            </div>
          ))}
          {significance.recommendation && (
            <div
              style={{
                marginTop: "8px",
                fontSize: "11px",
                fontFamily: "var(--font-body)",
                color: significance.is_significant ? "var(--accent-dim)" : "var(--text-muted)",
                lineHeight: "1.5",
              }}
            >
              {significance.recommendation}
            </div>
          )}
        </div>
      )}

      {/* Footer notice for no winner */}
      {results.length > 0 && !hasWinner && !significance?.is_significant && (
        <div
          style={{
            margin: "0 20px 16px",
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
          Insufficient sample size to declare a winner. Gather more engagement
          data before the next cycle.
        </div>
      )}

      {/* Actions */}
      <div
        style={{
          padding: "12px 20px",
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          gap: "8px",
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          className="btn-accent"
          disabled={isPendingAction}
          onClick={handleNextCycle}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            opacity: isPendingAction ? 0.6 : undefined,
          }}
        >
          {isPendingAction ? (
            <>
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
              Processing…
            </>
          ) : (
            "Run Next Cycle"
          )}
        </button>
      </div>
    </div>
  );
}
