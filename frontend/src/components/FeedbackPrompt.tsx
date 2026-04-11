import { useState } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Props {
  frame: UIFrame;
  onAction: (
    instanceId: string,
    actionId: string,
    payload: Record<string, unknown>,
  ) => void;
}

// ---------------------------------------------------------------------------
// Icon
// ---------------------------------------------------------------------------

function ClockIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FeedbackPrompt({ frame, onAction }: Props) {
  const message =
    (frame.props.message as string) ??
    "No engagement events received yet. You can report results manually or wait for webhook events.";

  const [clickedId, setClickedId] = useState<string | null>(null);
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);
  const isActed = clickedId !== null;

  function handleAction(action: UIAction) {
    if (isActed) return;
    setClickedId(action.id);
    onAction(frame.instance_id, action.id, action.payload);
  }

  return (
    <div
      className="surface-card overflow-hidden animate-fade-in-up"
      style={{
        opacity: isActed ? 0.65 : 1,
        transition: "opacity 0.3s",
        boxShadow: "0 2px 16px rgba(0,0,0,0.25)",
      }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid var(--warning)",
          padding: "14px 20px",
          borderBottom:
            frame.actions.length > 0 ? "1px solid var(--border-subtle)" : "none",
          display: "flex",
          alignItems: "center",
          gap: "10px",
        }}
      >
        <span style={{ color: "var(--warning)" }}>
          <ClockIcon />
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
          Awaiting Feedback
        </span>
      </div>

      {/* Message body */}
      <div style={{ padding: "14px 20px" }}>
        <p
          style={{
            fontSize: "13px",
            lineHeight: "1.65",
            color: "var(--text-secondary)",
          }}
        >
          {message}
        </p>
      </div>

      {/* Actions */}
      {frame.actions.length > 0 && (
        <div
          className="flex flex-wrap gap-2"
          style={{
            padding: "12px 20px",
            borderTop: "1px solid var(--border-subtle)",
          }}
        >
          {frame.actions.map((action) => {
            const isClicked = clickedId === action.id;
            const isPrimary = action.action_type === "manual_feedback";

            return (
              <button
                key={action.id}
                type="button"
                disabled={isActed || isPendingAction}
                onClick={() => handleAction(action)}
                className={isPrimary ? "btn-accent" : "btn-ghost"}
                style={
                  isActed
                    ? {
                        opacity: isClicked ? 1 : 0.35,
                        cursor: "default",
                        ...(isClicked && isPrimary
                          ? {
                              background: "var(--accent)",
                              borderColor: "var(--accent)",
                            }
                          : {}),
                      }
                    : undefined
                }
              >
                {isClicked && isPendingAction ? (
                  <>
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    {action.label}
                  </>
                ) : (
                  action.label
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
