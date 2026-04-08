import { useState } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";

interface Channel {
  id: string;
  label: string;
  icon: string;
  description: string;
  prospect_count: number;
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

function ChannelIcon({ icon }: { icon: string }) {
  const lower = icon.toLowerCase();

  if (lower === "email" || lower === "mail") {
    return (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="4" width="20" height="16" rx="2" />
        <path d="M22 7l-10 7L2 7" />
      </svg>
    );
  }

  if (lower === "linkedin") {
    return (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
        <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
      </svg>
    );
  }

  // Fallback: generic broadcast icon
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="2" />
      <path d="M16.24 7.76a6 6 0 010 8.49M7.76 16.24a6 6 0 010-8.49" />
      <path d="M19.07 4.93a10 10 0 010 14.14M4.93 19.07a10 10 0 010-14.14" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Channel color map
// ---------------------------------------------------------------------------

const CHANNEL_THEME: Record<string, { color: string; glow: string }> = {
  email:    { color: "var(--signal-audience)", glow: "rgba(77,171,247,0.15)" },
  linkedin: { color: "var(--signal-market)",   glow: "rgba(255,212,59,0.15)" },
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ChannelSelector({ frame, onAction }: Props) {
  const channels = (frame.props.available_channels as Channel[]) ?? [];
  const initialSelected = (frame.props.selected_channels as string[]) ?? [];
  const [selected, setSelected] = useState<Set<string>>(new Set(initialSelected));

  const confirmAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "confirm_channels" ||
      a.id === "confirm-channels"
  );

  function toggleChannel(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleConfirm() {
    if (selected.size === 0) return;
    const ids = Array.from(selected);
    if (confirmAction) {
      onAction(frame.instance_id, confirmAction.id, {
        ...confirmAction.payload,
        selected_channels: ids,
      });
    } else {
      onAction(frame.instance_id, "confirm_channels", {
        action: "confirm_channels",
        selected_channels: ids,
      });
    }
  }

  if (channels.length === 0) {
    return (
      <div className="surface-card" style={{ padding: "20px 24px", color: "var(--text-muted)", fontSize: "13px" }}>
        No channels available.
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
            Select Channels
          </span>
        </div>
        <span
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            color: selected.size > 0 ? "var(--accent)" : "var(--text-muted)",
          }}
        >
          {selected.size} selected
        </span>
      </div>

      {/* Channel cards */}
      <div
        style={{
          padding: "16px 20px",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "12px",
        }}
      >
        {channels.map((ch) => {
          const isSelected = selected.has(ch.id);
          const theme = CHANNEL_THEME[ch.id.toLowerCase()] ??
                        CHANNEL_THEME[ch.label.toLowerCase()] ??
                        { color: "var(--accent)", glow: "var(--accent-glow)" };

          return (
            <button
              key={ch.id}
              type="button"
              onClick={() => toggleChannel(ch.id)}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-start",
                gap: "12px",
                padding: "16px",
                borderRadius: "var(--radius-md)",
                background: isSelected ? theme.glow : "var(--bg-surface-3)",
                border: `1px solid ${isSelected ? theme.color : "var(--border-default)"}`,
                boxShadow: isSelected
                  ? `0 0 24px ${theme.glow}, inset 0 0 0 1px ${theme.color}`
                  : "none",
                cursor: "pointer",
                textAlign: "left",
                transition: "all 0.2s ease",
                outline: "none",
              }}
            >
              {/* Icon + toggle indicator row */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
                <div
                  style={{
                    color: isSelected ? theme.color : "var(--text-muted)",
                    transition: "color 0.2s",
                  }}
                >
                  <ChannelIcon icon={ch.icon || ch.label} />
                </div>

                {/* Toggle pill */}
                <div
                  style={{
                    width: "32px",
                    height: "18px",
                    borderRadius: "9px",
                    background: isSelected ? theme.color : "var(--bg-elevated)",
                    border: `1px solid ${isSelected ? theme.color : "var(--border-default)"}`,
                    position: "relative",
                    transition: "all 0.2s ease",
                    flexShrink: 0,
                  }}
                >
                  <div
                    style={{
                      width: "12px",
                      height: "12px",
                      borderRadius: "50%",
                      background: isSelected ? "#fff" : "var(--text-muted)",
                      position: "absolute",
                      top: "2px",
                      left: isSelected ? "16px" : "2px",
                      transition: "left 0.2s ease, background 0.2s ease",
                    }}
                  />
                </div>
              </div>

              {/* Label + prospect count */}
              <div style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%" }}>
                <span
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: "14px",
                    fontWeight: 700,
                    color: isSelected ? theme.color : "var(--text-primary)",
                    letterSpacing: "-0.01em",
                    transition: "color 0.2s",
                  }}
                >
                  {ch.label}
                </span>
                <span
                  style={{
                    fontSize: "10px",
                    fontFamily: "var(--font-mono)",
                    color: isSelected ? theme.color : "var(--text-muted)",
                    background: isSelected ? `${theme.color}18` : "var(--bg-elevated)",
                    border: `1px solid ${isSelected ? `${theme.color}40` : "var(--border-subtle)"}`,
                    borderRadius: "4px",
                    padding: "2px 6px",
                    whiteSpace: "nowrap",
                    transition: "all 0.2s",
                  }}
                >
                  {ch.prospect_count} prospect{ch.prospect_count !== 1 ? "s" : ""}
                </span>
              </div>

              {/* Description */}
              <p
                style={{
                  fontSize: "12px",
                  lineHeight: "1.6",
                  color: "var(--text-secondary)",
                  margin: 0,
                }}
              >
                {ch.description}
              </p>
            </button>
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
          justifyContent: "flex-end",
          gap: "8px",
        }}
      >
        {frame.actions
          .filter((a) => a.action_type !== "confirm_channels" && a.id !== "confirm-channels")
          .map((action) => (
            <button
              key={action.id}
              type="button"
              className="btn-ghost"
              onClick={() => onAction(frame.instance_id, action.id, action.payload)}
            >
              {action.label}
            </button>
          ))}
        <button
          type="button"
          className="btn-accent"
          disabled={selected.size === 0}
          onClick={handleConfirm}
          style={{ opacity: selected.size === 0 ? 0.4 : 1 }}
        >
          Confirm Channels ({selected.size})
        </button>
      </div>
    </div>
  );
}
