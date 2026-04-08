import { useState } from "react";
import type { UIFrame } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Finding {
  claim: string;
  signal_type: string;
  confidence: number;
  actionable_implication: string;
}

interface BriefingProps {
  executive_summary: string;
  top_findings: Finding[];
  content_angles: string[];
  gaps: string[];
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

const SIGNAL_STYLES: Record<string, { color: string; bg: string; label: string }> = {
  competitor: { color: "var(--signal-competitor)", bg: "rgba(255,107,107,0.1)", label: "COMP" },
  audience:   { color: "var(--signal-audience)",   bg: "rgba(77,171,247,0.1)",  label: "AUD" },
  channel:    { color: "var(--signal-channel)",    bg: "rgba(81,207,102,0.1)",  label: "CHAN" },
  market:     { color: "var(--signal-market)",     bg: "rgba(255,212,59,0.1)",  label: "MKT" },
};

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  const barColor = pct >= 70 ? "var(--success)" : pct >= 40 ? "var(--warning)" : "var(--danger)";

  return (
    <div className="flex items-center gap-2" style={{ minWidth: "90px" }}>
      <div style={{ width: "60px", height: "3px", borderRadius: "2px", background: "var(--bg-base)", overflow: "hidden" }}>
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            borderRadius: "2px",
            background: barColor,
            boxShadow: `0 0 8px ${barColor}`,
            transition: "width 0.6s ease-out",
          }}
        />
      </div>
      <span style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--text-muted)", minWidth: "28px" }}>
        {pct}%
      </span>
    </div>
  );
}

function SignalBadge({ type }: { type: string }) {
  const s = SIGNAL_STYLES[type] ?? { color: "var(--text-muted)", bg: "var(--bg-elevated)", label: type.slice(0, 4).toUpperCase() };
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: "9px",
        fontWeight: 700,
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.08em",
        color: s.color,
        background: s.bg,
        border: `1px solid ${s.color}22`,
        borderRadius: "3px",
        padding: "2px 6px",
      }}
    >
      {s.label}
    </span>
  );
}

export default function BriefingCard({ frame, onAction }: Props) {
  const briefing = (frame.props.briefing ?? frame.props) as BriefingProps;
  const findingCount = (frame.props.finding_count as number) ?? briefing.top_findings?.length ?? 0;
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const {
    executive_summary = "",
    top_findings = [],
    content_angles = [],
    gaps = [],
  } = briefing;

  return (
    <div
      className="surface-card overflow-hidden"
      style={{
        boxShadow: "0 0 40px rgba(0,212,170,0.04), 0 4px 24px rgba(0,0,0,0.3)",
      }}
    >
      {/* Header with accent top border */}
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
        <div className="flex items-center gap-2.5">
          <div
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              background: "var(--accent)",
              boxShadow: "0 0 8px var(--accent-glow-strong)",
            }}
          />
          <span style={{ fontFamily: "var(--font-display)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
            Intelligence Briefing
          </span>
        </div>
        {findingCount > 0 && (
          <span style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
            {findingCount} signal{findingCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      <div style={{ padding: "16px 20px" }} className="space-y-5">
        {/* Executive summary */}
        {executive_summary && (
          <p style={{ fontSize: "13px", lineHeight: "1.7", color: "var(--text-secondary)" }}>
            {executive_summary}
          </p>
        )}

        {/* Top findings */}
        {top_findings.length > 0 && (
          <div>
            <h4 style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-muted)", marginBottom: "8px" }}>
              Top Findings
            </h4>
            <div className="space-y-1">
              {top_findings.map((f, i) => {
                const isExpanded = expandedIdx === i;
                return (
                  <button
                    key={i}
                    type="button"
                    className="w-full text-left"
                    style={{
                      display: "block",
                      padding: "8px 10px",
                      borderRadius: "var(--radius-sm)",
                      background: isExpanded ? "var(--bg-elevated)" : "transparent",
                      border: "1px solid transparent",
                      cursor: "pointer",
                      transition: "all 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      if (!isExpanded) e.currentTarget.style.background = "var(--bg-surface-3)";
                    }}
                    onMouseLeave={(e) => {
                      if (!isExpanded) e.currentTarget.style.background = "transparent";
                    }}
                    onClick={() => setExpandedIdx(isExpanded ? null : i)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <SignalBadge type={f.signal_type} />
                        <span style={{ fontSize: "12.5px", color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {f.claim}
                        </span>
                      </div>
                      <ConfidenceBar value={f.confidence} />
                    </div>
                    {isExpanded && f.actionable_implication && (
                      <p
                        className="animate-fade-in"
                        style={{ marginTop: "8px", paddingLeft: "2px", fontSize: "11.5px", lineHeight: "1.6", color: "var(--text-muted)" }}
                      >
                        {f.actionable_implication}
                      </p>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Content angles */}
        {content_angles.length > 0 && (
          <div>
            <h4 style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-muted)", marginBottom: "8px" }}>
              Content Angles
            </h4>
            <div className="flex flex-wrap gap-2">
              {content_angles.map((angle, i) => (
                <span
                  key={i}
                  style={{
                    fontSize: "11px",
                    fontWeight: 500,
                    color: "var(--accent)",
                    background: "var(--accent-glow)",
                    border: "1px solid rgba(0,212,170,0.12)",
                    borderRadius: "20px",
                    padding: "4px 12px",
                  }}
                >
                  {angle}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Research gaps */}
        {gaps.length > 0 && (
          <div>
            <h4 style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-muted)", marginBottom: "6px" }}>
              Research Gaps
            </h4>
            <div className="space-y-1">
              {gaps.map((gap, i) => (
                <div key={i} className="flex items-start gap-2" style={{ fontSize: "11.5px", color: "var(--text-muted)" }}>
                  <span style={{ color: "var(--warning)", fontSize: "8px", marginTop: "5px" }}>◆</span>
                  {gap}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Action buttons */}
      {frame.actions.length > 0 && (
        <div
          className="flex flex-wrap gap-2"
          style={{ padding: "12px 20px", borderTop: "1px solid var(--border-subtle)" }}
        >
          {frame.actions.map((action, i) => (
            <button
              key={action.id}
              type="button"
              disabled={isPendingAction}
              className={i === 0 ? "btn-accent" : "btn-ghost"}
              style={{ opacity: isPendingAction ? 0.6 : undefined }}
              onClick={() => onAction(frame.instance_id, action.id, action.payload)}
            >
              {isPendingAction ? (
                <>
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" style={{ marginRight: "6px" }} />
                  Queuing…
                </>
              ) : (
                action.label
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
