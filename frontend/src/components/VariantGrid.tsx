import { useState } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface ContentVariant {
  id: string;
  intended_channel: string;
  hypothesis: string;
  success_metric: string;
  source_finding_ids: string[];
  subject_line?: string | null;
  body: string;
  cta: string;
  angle_label?: string | null;
  personalized_for?: string | null;
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

// ---------------------------------------------------------------------------
// Style maps
// ---------------------------------------------------------------------------

const CHANNEL_STYLES: Record<string, { color: string; bg: string; label: string }> = {
  email:    { color: "var(--signal-audience)", bg: "rgba(77,171,247,0.12)",  label: "EMAIL" },
  linkedin: { color: "var(--signal-market)",   bg: "rgba(255,212,59,0.12)",  label: "LINKEDIN" },
  twitter:  { color: "#74c0fc",                bg: "rgba(116,192,252,0.12)", label: "TWITTER" },
};

const ANGLE_COLORS: Record<string, string> = {
  "competitor-gap":  "var(--signal-competitor)",
  "roi-first":       "var(--signal-channel)",
  "pain-led":        "var(--signal-audience)",
  "social-proof":    "var(--signal-market)",
  "authority":       "#cc5de8",
  "strategic-vision":"#74c0fc",
};

const FINDING_CHIP_COLORS = [
  "var(--signal-competitor)",
  "var(--signal-audience)",
  "var(--signal-channel)",
  "var(--signal-market)",
  "#cc5de8",
  "#74c0fc",
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ChannelBadge({ channel }: { channel: string }) {
  const s = CHANNEL_STYLES[channel.toLowerCase()] ?? {
    color: "var(--text-muted)",
    bg: "var(--bg-elevated)",
    label: channel.toUpperCase(),
  };
  return (
    <span
      style={{
        fontSize: "9px",
        fontWeight: 700,
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.08em",
        color: s.color,
        background: s.bg,
        border: `1px solid ${s.color}33`,
        borderRadius: "3px",
        padding: "2px 7px",
      }}
    >
      {s.label}
    </span>
  );
}

function AnglePill({ label }: { label: string }) {
  const color = ANGLE_COLORS[label.toLowerCase()] ?? "var(--text-muted)";
  return (
    <span
      style={{
        fontSize: "9.5px",
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        color,
        background: `${color}18`,
        border: `1px solid ${color}33`,
        borderRadius: "4px",
        padding: "2px 8px",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

function MetricBadge({ metric }: { metric: string }) {
  return (
    <span
      style={{
        fontSize: "9.5px",
        fontFamily: "var(--font-mono)",
        color: "var(--success)",
        background: "rgba(81,207,102,0.1)",
        border: "1px solid rgba(81,207,102,0.3)",
        borderRadius: "4px",
        padding: "2px 8px",
        whiteSpace: "nowrap",
      }}
    >
      {metric}
    </span>
  );
}

function FindingChip({ findingId, index }: { findingId: string; index: number }) {
  const color = FINDING_CHIP_COLORS[index % FINDING_CHIP_COLORS.length];
  return (
    <span
      style={{
        fontSize: "9.5px",
        fontFamily: "var(--font-mono)",
        fontWeight: 600,
        color,
        background: `${color}14`,
        border: `1px solid ${color}30`,
        borderRadius: "3px",
        padding: "1px 6px",
        whiteSpace: "nowrap",
      }}
    >
      Finding #{findingId.slice(-4) || findingId}
    </span>
  );
}

function BodyPreview({ text, expanded }: { text: string; expanded: boolean }) {
  const preview = expanded ? text : text.slice(0, 180) + (text.length > 180 ? "…" : "");
  return (
    <p
      style={{
        margin: 0,
        fontSize: "12px",
        lineHeight: "1.7",
        color: "var(--text-secondary)",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {preview}
    </p>
  );
}

function ABSplitIndicator({ selectedCount }: { selectedCount: number }) {
  if (selectedCount < 2) return null;

  const pct = Math.round(100 / selectedCount);
  const labels = Array.from({ length: selectedCount }, (_, i) =>
    String.fromCharCode(65 + i)
  );

  return (
    <div
      style={{
        margin: "0 16px",
        padding: "10px 14px",
        background: "var(--bg-surface-3)",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border-subtle)",
      }}
    >
      <div
        style={{
          fontSize: "9px",
          fontWeight: 700,
          fontFamily: "var(--font-mono)",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "var(--accent)",
          marginBottom: "8px",
        }}
      >
        A/B Split Plan
      </div>
      <div style={{ display: "flex", gap: "6px", marginBottom: "8px" }}>
        {labels.map((label, i) => (
          <div
            key={label}
            style={{
              flex: 1,
              height: "4px",
              borderRadius: "2px",
              background: FINDING_CHIP_COLORS[i % FINDING_CHIP_COLORS.length],
              opacity: 0.7,
            }}
          />
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "12px" }}>
        {labels.map((label, i) => (
          <span
            key={label}
            style={{
              fontSize: "11px",
              fontFamily: "var(--font-mono)",
              color: "var(--text-secondary)",
            }}
          >
            <span
              style={{
                fontWeight: 700,
                color: FINDING_CHIP_COLORS[i % FINDING_CHIP_COLORS.length],
              }}
            >
              Variant {label}
            </span>
            {" → "}
            {pct}% of prospects
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function VariantGrid({ frame, onAction }: Props) {
  const variants = (frame.props.variants as ContentVariant[]) ?? [];
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const confirmAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "confirm_variants" ||
      a.action_type === "deploy_variants" ||
      a.id === "confirm-selected" ||
      a.id === "deploy-selected"
  );

  const refineAction = frame.actions.find(
    (a: UIAction) => a.action_type === "content_refine" || a.id === "refine-content"
  );
  const hasFooterActions = Boolean(confirmAction || refineAction);

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleSelectAll() {
    setSelected(new Set(variants.map((v) => v.id)));
  }

  function handleClearAll() {
    setSelected(new Set());
  }

  function handleConfirm() {
    if (selected.size === 0) return;
    const ids = Array.from(selected);
    if (confirmAction) {
      onAction(frame.instance_id, confirmAction.id, {
        ...confirmAction.payload,
        variant_ids: ids,
      });
    } else {
      onAction(frame.instance_id, "confirm_variants", {
        action: "confirm_variants",
        variant_ids: ids,
      });
    }
  }

  function handleRefine() {
    if (refineAction) {
      onAction(frame.instance_id, refineAction.id, refineAction.payload);
    } else {
      onAction(frame.instance_id, "refine-content", {});
    }
  }

  if (variants.length === 0) {
    return (
      <div className="surface-card" style={{ padding: "20px 24px", color: "var(--text-muted)", fontSize: "13px" }}>
        No content variants generated yet.
      </div>
    );
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
          gap: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              background: "var(--accent)",
              boxShadow: "0 0 8px var(--accent-glow-strong)",
              flexShrink: 0,
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
            Content Variants
          </span>
        </div>
        <span
          style={{
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
            color: selected.size > 0 ? "var(--accent)" : "var(--text-muted)",
          }}
        >
          {selected.size}/{variants.length} selected
        </span>
      </div>

      {/* Variant cards — grid on desktop, stacked on mobile */}
      <div
        style={{
          padding: "16px 16px 8px",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: "12px",
        }}
      >
        {variants.map((variant) => {
          const isSelected = selected.has(variant.id);
          const isExpanded = expanded.has(variant.id);
          return (
            <div
              key={variant.id}
              onClick={() => toggleSelect(variant.id)}
              style={{
                padding: "14px 16px",
                borderRadius: "var(--radius-md)",
                cursor: "pointer",
                background: isSelected ? "var(--accent-glow)" : "var(--bg-surface-3)",
                border: `1px solid ${isSelected ? "var(--accent)" : "var(--border-default)"}`,
                boxShadow: isSelected
                  ? "0 0 20px var(--accent-glow-strong), inset 0 0 0 1px var(--accent)"
                  : "none",
                transition: "all 0.2s ease",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }}
            >
              {/* Row 1: channel + angle + checkbox */}
              <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                <ChannelBadge channel={variant.intended_channel} />
                {variant.angle_label && <AnglePill label={variant.angle_label} />}
                {variant.personalized_for && (
                  <span
                    style={{
                      fontSize: "9px",
                      fontWeight: 600,
                      fontFamily: "var(--font-mono)",
                      color: "#22d3ee",
                      background: "rgba(34,211,238,0.1)",
                      border: "1px solid rgba(34,211,238,0.3)",
                      borderRadius: "3px",
                      padding: "2px 7px",
                      letterSpacing: "0.03em",
                    }}
                  >
                    PERSONALIZED
                  </span>
                )}
                <div style={{ marginLeft: "auto" }}>
                  <div
                    style={{
                      width: "16px",
                      height: "16px",
                      borderRadius: "4px",
                      border: `1.5px solid ${isSelected ? "var(--accent)" : "var(--border-default)"}`,
                      background: isSelected ? "var(--accent)" : "transparent",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                      transition: "all 0.15s ease",
                    }}
                  >
                    {isSelected && (
                      <svg width="8" height="6" viewBox="0 0 8 6" fill="none">
                        <path d="M1 3L3 5L7 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                  </div>
                </div>
              </div>

              {/* Row 2: hypothesis */}
              <p
                style={{
                  margin: 0,
                  fontSize: "12px",
                  fontStyle: "italic",
                  color: "var(--text-secondary)",
                  lineHeight: "1.55",
                }}
              >
                {variant.hypothesis}
              </p>

              {/* Row 3: subject line (email only) */}
              {variant.subject_line && (
                <div
                  style={{
                    padding: "5px 10px",
                    background: "var(--bg-elevated)",
                    borderRadius: "4px",
                    fontSize: "12px",
                    fontWeight: 600,
                    color: "var(--text-primary)",
                  }}
                >
                  Subject: {variant.subject_line}
                </div>
              )}

              {/* Row 4: body preview */}
              <div
                onClick={(e) => {
                  e.stopPropagation();
                  toggleExpand(variant.id);
                }}
              >
                <BodyPreview text={variant.body} expanded={isExpanded} />
                {variant.body.length > 180 && (
                  <button
                    type="button"
                    style={{
                      marginTop: "4px",
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      fontSize: "11px",
                      color: "var(--accent)",
                      padding: 0,
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {isExpanded ? "Show less" : "Show more"}
                  </button>
                )}
              </div>

              {/* Row 5: CTA */}
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 600,
                  color: "var(--accent)",
                  background: "var(--accent-glow)",
                  border: "1px solid rgba(0,212,170,0.2)",
                  borderRadius: "4px",
                  padding: "3px 8px",
                  fontFamily: "var(--font-mono)",
                  alignSelf: "flex-start",
                }}
              >
                CTA: {variant.cta}
              </span>

              {/* Row 6: source finding chips */}
              {variant.source_finding_ids.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                  {variant.source_finding_ids.map((fid, i) => (
                    <FindingChip key={fid} findingId={fid} index={i} />
                  ))}
                </div>
              )}

              {/* Row 7: success metric */}
              <div style={{ marginTop: "auto", paddingTop: "4px" }}>
                <MetricBadge metric={variant.success_metric} />
              </div>
            </div>
          );
        })}
      </div>

      {/* A/B split indicator */}
      <ABSplitIndicator selectedCount={selected.size} />

      {hasFooterActions && (
        <div
          style={{
            padding: "12px 16px",
            borderTop: "1px solid var(--border-subtle)",
            marginTop: "8px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            flexWrap: "wrap",
          }}
        >
          <button type="button" className="btn-ghost" onClick={handleSelectAll} disabled={isPendingAction}>
            Select All
          </button>
          <button type="button" className="btn-ghost" onClick={handleClearAll} disabled={isPendingAction}>
            Clear
          </button>
          {refineAction && (
            <button
              type="button"
              className="btn-ghost"
              disabled={isPendingAction}
              onClick={handleRefine}
              style={{
                color: "var(--warning)",
                borderColor: "rgba(255,212,59,0.3)",
              }}
            >
              Refine Content
            </button>
          )}
          {confirmAction && (
            <button
              type="button"
              className="btn-accent"
              disabled={selected.size === 0 || isPendingAction}
              onClick={handleConfirm}
              style={{
                marginLeft: "auto",
                opacity: selected.size === 0 || isPendingAction ? 0.4 : 1,
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              {isPendingAction ? (
                <>
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  Queuing…
                </>
              ) : (
                `Confirm Selected Variants (${selected.size})`
              )}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
