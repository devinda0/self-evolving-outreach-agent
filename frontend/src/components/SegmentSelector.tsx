import { useState } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Segment {
  id: string;
  label: string;
  description: string;
  recommended_angle: string;
  prospect_count: number;
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export default function SegmentSelector({ frame, onAction }: Props) {
  const segments = (frame.props.segments as Segment[]) ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const selectAction = frame.actions.find(
    (a: UIAction) => a.action_type === "select_segment" || a.id === "select_segment"
  );

  function handleUseSegment() {
    if (!selectedId) return;
    if (selectAction) {
      onAction(frame.instance_id, selectAction.id, {
        ...selectAction.payload,
        segment_id: selectedId,
      });
    } else {
      onAction(frame.instance_id, "select_segment", { segment_id: selectedId });
    }
  }

  return (
    <div
      className="surface-card overflow-hidden"
      style={{ boxShadow: "0 0 40px rgba(0,212,170,0.04), 0 4px 24px rgba(0,0,0,0.3)" }}
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
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "13px",
              fontWeight: 700,
              color: "var(--text-primary)",
              letterSpacing: "-0.01em",
            }}
          >
            Select Target Segment
          </span>
        </div>
        <span
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          {segments.length} segment{segments.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Segment cards */}
      <div
        style={{
          padding: "16px 20px",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "12px",
        }}
      >
        {segments.map((seg) => {
          const isSelected = selectedId === seg.id;
          return (
            <button
              key={seg.id}
              type="button"
              onClick={() => setSelectedId(isSelected ? null : seg.id)}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-start",
                gap: "10px",
                padding: "14px 16px",
                borderRadius: "var(--radius-md)",
                background: isSelected ? "var(--accent-glow)" : "var(--bg-surface-2)",
                border: `1px solid ${isSelected ? "var(--accent)" : "var(--border-default)"}`,
                boxShadow: isSelected
                  ? "0 0 20px var(--accent-glow-strong), inset 0 0 0 1px var(--accent)"
                  : "none",
                cursor: "pointer",
                textAlign: "left",
                transition: "all 0.2s ease",
                outline: "none",
              }}
              onMouseEnter={(e) => {
                if (!isSelected)
                  e.currentTarget.style.border = "1px solid var(--border-hover)";
              }}
              onMouseLeave={(e) => {
                if (!isSelected)
                  e.currentTarget.style.border = "1px solid var(--border-default)";
              }}
            >
              {/* Label row */}
              <div className="flex items-center justify-between w-full gap-2">
                <span
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: "13px",
                    fontWeight: 700,
                    color: isSelected ? "var(--accent)" : "var(--text-primary)",
                    letterSpacing: "-0.01em",
                    transition: "color 0.2s",
                  }}
                >
                  {seg.label}
                </span>
                {/* Prospect count badge */}
                <span
                  style={{
                    fontSize: "10px",
                    fontFamily: "var(--font-mono)",
                    color: isSelected ? "var(--accent)" : "var(--text-muted)",
                    background: isSelected ? "rgba(0,212,170,0.12)" : "var(--bg-elevated)",
                    border: `1px solid ${isSelected ? "rgba(0,212,170,0.3)" : "var(--border-subtle)"}`,
                    borderRadius: "4px",
                    padding: "2px 6px",
                    whiteSpace: "nowrap",
                    transition: "all 0.2s",
                  }}
                >
                  {seg.prospect_count} prospects
                </span>
              </div>

              {/* Description */}
              <p
                style={{
                  fontSize: "12px",
                  lineHeight: "1.65",
                  color: "var(--text-secondary)",
                  margin: 0,
                }}
              >
                {seg.description}
              </p>

              {/* Recommended angle pill */}
              <span
                style={{
                  display: "inline-block",
                  fontSize: "10px",
                  fontWeight: 600,
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.04em",
                  color: "var(--signal-channel)",
                  background: "rgba(81,207,102,0.1)",
                  border: "1px solid rgba(81,207,102,0.2)",
                  borderRadius: "4px",
                  padding: "3px 8px",
                }}
              >
                {seg.recommended_angle}
              </span>

              {/* "Use This Segment" CTA — only when this card is selected */}
              {isSelected && (
                <button
                  type="button"
                  disabled={isPendingAction}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleUseSegment();
                  }}
                  style={{
                    alignSelf: "stretch",
                    marginTop: "2px",
                    padding: "8px 14px",
                    borderRadius: "var(--radius-sm)",
                    background: isPendingAction ? "var(--bg-elevated)" : "var(--accent)",
                    border: "none",
                    color: isPendingAction ? "var(--text-muted)" : "#06070a",
                    fontSize: "11.5px",
                    fontWeight: 700,
                    fontFamily: "var(--font-body)",
                    letterSpacing: "0.02em",
                    cursor: isPendingAction ? "default" : "pointer",
                    boxShadow: isPendingAction ? "none" : "0 0 16px var(--accent-glow-strong)",
                    transition: "all 0.15s",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "6px",
                  }}
                  onMouseEnter={(e) => {
                    if (!isPendingAction) e.currentTarget.style.opacity = "0.88";
                  }}
                  onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
                >
                  {isPendingAction ? (
                    <>
                      <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                      Queuing…
                    </>
                  ) : (
                    "Use This Segment →"
                  )}
                </button>
              )}
            </button>
          );
        })}
      </div>

      {/* Empty state */}
      {segments.length === 0 && (
        <div
          style={{
            padding: "32px 20px",
            textAlign: "center",
            color: "var(--text-muted)",
            fontSize: "12px",
            fontFamily: "var(--font-mono)",
          }}
        >
          No segments available.
        </div>
      )}
    </div>
  );
}
