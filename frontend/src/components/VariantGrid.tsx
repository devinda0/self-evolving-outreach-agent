import { useState } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";

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

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function VariantGrid({ frame, onAction }: Props) {
  const variants = (frame.props.variants as ContentVariant[]) ?? [];
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const deployAction = frame.actions.find(
    (a: UIAction) => a.action_type === "deploy_variants" || a.id === "deploy-selected"
  );

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

  function handleDeploy() {
    if (!deployAction || selected.size === 0) return;
    onAction(frame.instance_id, deployAction.id, {
      ...deployAction.payload,
      selected_variant_ids: Array.from(selected),
    });
  }

  if (variants.length === 0) {
    return (
      <div className="surface-card" style={{ padding: "20px 24px", color: "var(--text-muted)", fontSize: "13px" }}>
        No content variants generated yet.
      </div>
    );
  }

  return (
    <div className="surface-card overflow-hidden">
      {/* Header */}
      <div
        style={{
          padding: "10px 16px",
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
              boxShadow: "0 0 6px var(--accent)",
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "11px",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
            }}
          >
            Variant Grid — {variants.length} variants
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

      {/* Variant cards */}
      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {variants.map((variant, idx) => {
          const isSelected = selected.has(variant.id);
          const isExpanded = expanded.has(variant.id);
          return (
            <div
              key={variant.id}
              onClick={() => toggleSelect(variant.id)}
              style={{
                padding: "14px 16px",
                borderBottom: idx < variants.length - 1 ? "1px solid var(--border-subtle)" : "none",
                cursor: "pointer",
                background: isSelected ? "rgba(var(--accent-rgb, 99,102,241), 0.06)" : "transparent",
                borderLeft: isSelected ? "2px solid var(--accent)" : "2px solid transparent",
                transition: "background 0.15s ease, border-color 0.15s ease",
              }}
            >
              {/* Row 1: channel + angle + metric + select indicator */}
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px", flexWrap: "wrap" }}>
                <ChannelBadge channel={variant.intended_channel} />
                {variant.angle_label && <AnglePill label={variant.angle_label} />}
                <MetricBadge metric={variant.success_metric} />
                <div style={{ marginLeft: "auto" }}>
                  <div
                    style={{
                      width: "14px",
                      height: "14px",
                      borderRadius: "3px",
                      border: `1.5px solid ${isSelected ? "var(--accent)" : "var(--border-subtle)"}`,
                      background: isSelected ? "var(--accent)" : "transparent",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
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
                  margin: "0 0 8px 0",
                  fontSize: "12px",
                  fontStyle: "italic",
                  color: "var(--text-secondary)",
                  lineHeight: "1.5",
                }}
              >
                {variant.hypothesis}
              </p>

              {/* Row 3: subject line (email only) */}
              {variant.subject_line && (
                <div
                  style={{
                    marginBottom: "8px",
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

              {/* Row 5: CTA + finding refs */}
              <div
                style={{
                  marginTop: "10px",
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  flexWrap: "wrap",
                }}
              >
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 600,
                    color: "var(--accent)",
                    background: "rgba(var(--accent-rgb,99,102,241),0.1)",
                    border: "1px solid rgba(var(--accent-rgb,99,102,241),0.25)",
                    borderRadius: "4px",
                    padding: "2px 8px",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  CTA: {variant.cta}
                </span>
                {variant.source_finding_ids.length > 0 && (
                  <span
                    style={{
                      fontSize: "10px",
                      color: "var(--text-muted)",
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    Sources: {variant.source_finding_ids.length} finding{variant.source_finding_ids.length !== 1 ? "s" : ""}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer actions */}
      <div
        style={{
          padding: "12px 16px",
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          gap: "8px",
          flexWrap: "wrap",
        }}
      >
        <button type="button" className="btn-ghost" onClick={handleSelectAll}>
          Select all
        </button>
        <button type="button" className="btn-ghost" onClick={handleClearAll}>
          Clear
        </button>
        <button
          type="button"
          className="btn-accent"
          disabled={selected.size === 0}
          onClick={handleDeploy}
          style={{ marginLeft: "auto", opacity: selected.size === 0 ? 0.4 : 1 }}
        >
          Deploy selected ({selected.size})
        </button>
      </div>
    </div>
  );
}
