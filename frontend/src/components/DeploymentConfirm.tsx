import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface ChannelBreakdown {
  channel: string;
  count: number;
}

interface ABPlan {
  cohort_a: { variant_label: string; prospect_count: number };
  cohort_b: { variant_label: string; prospect_count: number };
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

function WarningIcon() {
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
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function RocketIcon() {
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
      <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 00-2.91-.09z" />
      <path d="M12 15l-3-3a22 22 0 012-3.95A12.88 12.88 0 0122 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 01-4 2z" />
      <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0" />
      <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Channel style map
// ---------------------------------------------------------------------------

const CHANNEL_STYLES: Record<string, { color: string; label: string }> = {
  email: { color: "var(--signal-audience)", label: "Email" },
  linkedin: { color: "var(--signal-market)", label: "LinkedIn" },
  twitter: { color: "#74c0fc", label: "Twitter" },
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function DeploymentConfirm({ frame, onAction }: Props) {
  const variantCount = (frame.props.variant_count as number) ?? 0;
  const prospectCount = (frame.props.prospect_count as number) ?? 0;
  const channelBreakdown =
    (frame.props.channel_breakdown as ChannelBreakdown[]) ?? [];
  const abPlan = frame.props.ab_plan as ABPlan | undefined;
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const confirmAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "confirm_deploy" || a.id === "confirm-deploy",
  );
  const cancelAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "cancel_deploy" || a.id === "cancel-deploy",
  );

  function handleConfirm() {
    if (confirmAction) {
      onAction(frame.instance_id, confirmAction.id, {
        ...confirmAction.payload,
        action: "confirm_deploy",
      });
    } else {
      onAction(frame.instance_id, "confirm_deploy", {
        action: "confirm_deploy",
      });
    }
  }

  function handleCancel() {
    if (cancelAction) {
      onAction(frame.instance_id, cancelAction.id, {
        ...cancelAction.payload,
        action: "cancel_deploy",
      });
    } else {
      onAction(frame.instance_id, "cancel_deploy", {
        action: "cancel_deploy",
      });
    }
  }

  // Build the summary sentence
  const channelParts = channelBreakdown.map((ch) => {
    const style = CHANNEL_STYLES[ch.channel.toLowerCase()];
    const label = style?.label ?? ch.channel;
    return `${ch.count} ${label} message${ch.count !== 1 ? "s" : ""}`;
  });
  const channelSummary = channelParts.join(" and ");

  return (
    <div
      className="surface-card overflow-hidden"
      style={{
        boxShadow:
          "0 0 40px rgba(0,212,170,0.04), 0 4px 24px rgba(0,0,0,0.3)",
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
            Deployment Confirmation
          </span>
        </div>
        <span
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          {variantCount} variant{variantCount !== 1 ? "s" : ""} ·{" "}
          {prospectCount} prospect{prospectCount !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Summary */}
      <div style={{ padding: "16px 20px" }}>
        <p
          style={{
            margin: 0,
            fontSize: "13px",
            lineHeight: "1.65",
            color: "var(--text-secondary)",
          }}
        >
          You&apos;re about to send{" "}
          <span style={{ color: "var(--accent)", fontWeight: 600 }}>
            {channelSummary || `${variantCount} message${variantCount !== 1 ? "s" : ""}`}
          </span>{" "}
          to{" "}
          <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
            {prospectCount} prospect{prospectCount !== 1 ? "s" : ""}
          </span>
          .
        </p>
      </div>

      {/* Channel breakdown pills */}
      {channelBreakdown.length > 0 && (
        <div
          style={{
            padding: "0 20px 12px",
            display: "flex",
            flexWrap: "wrap",
            gap: "8px",
          }}
        >
          {channelBreakdown.map((ch) => {
            const style =
              CHANNEL_STYLES[ch.channel.toLowerCase()] ?? {
                color: "var(--text-muted)",
                label: ch.channel,
              };
            return (
              <span
                key={ch.channel}
                style={{
                  fontSize: "10px",
                  fontWeight: 700,
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.06em",
                  color: style.color,
                  background: `${style.color}14`,
                  border: `1px solid ${style.color}33`,
                  borderRadius: "4px",
                  padding: "4px 10px",
                  textTransform: "uppercase",
                }}
              >
                {style.label}: {ch.count}
              </span>
            );
          })}
        </div>
      )}

      {/* A/B Split table */}
      {abPlan && (
        <div
          style={{
            margin: "0 20px 12px",
            background: "var(--bg-surface-3)",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border-subtle)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "8px 14px",
              borderBottom: "1px solid var(--border-subtle)",
            }}
          >
            <span
              style={{
                fontSize: "9px",
                fontWeight: 700,
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: "var(--accent)",
              }}
            >
              A/B Split Plan
            </span>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Cohort", "Variant", "Prospects"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "8px 14px",
                      fontSize: "9px",
                      fontWeight: 700,
                      fontFamily: "var(--font-mono)",
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      color: "var(--text-muted)",
                      textAlign: "left",
                      borderBottom: "1px solid var(--border-subtle)",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                {
                  label: "A",
                  variant: abPlan.cohort_a.variant_label,
                  count: abPlan.cohort_a.prospect_count,
                  color: "var(--signal-competitor)",
                },
                {
                  label: "B",
                  variant: abPlan.cohort_b.variant_label,
                  count: abPlan.cohort_b.prospect_count,
                  color: "var(--signal-audience)",
                },
              ].map((row) => (
                <tr key={row.label}>
                  <td
                    style={{
                      padding: "8px 14px",
                      fontSize: "12px",
                      fontWeight: 700,
                      fontFamily: "var(--font-mono)",
                      color: row.color,
                    }}
                  >
                    Cohort {row.label}
                  </td>
                  <td
                    style={{
                      padding: "8px 14px",
                      fontSize: "12px",
                      color: "var(--text-secondary)",
                    }}
                  >
                    {row.variant}
                  </td>
                  <td
                    style={{
                      padding: "8px 14px",
                      fontSize: "12px",
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    {row.count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Warning banner */}
      <div
        style={{
          margin: "0 20px 16px",
          padding: "10px 14px",
          borderRadius: "var(--radius-sm)",
          background: "rgba(255,212,59,0.08)",
          border: "1px solid rgba(255,212,59,0.25)",
          display: "flex",
          alignItems: "center",
          gap: "10px",
        }}
      >
        <span
          style={{
            color: "var(--signal-market)",
            flexShrink: 0,
          }}
        >
          <WarningIcon />
        </span>
        <span
          style={{
            fontSize: "11.5px",
            color: "var(--signal-market)",
            lineHeight: "1.5",
          }}
        >
          This will send real messages. Confirm to proceed.
        </span>
      </div>

      {/* Action buttons */}
      <div
        style={{
          padding: "12px 20px 16px",
          display: "flex",
          justifyContent: "flex-end",
          gap: "10px",
        }}
      >
        <button
          type="button"
          className="btn-ghost"
          disabled={isPendingAction}
          onClick={handleCancel}
          style={{
            fontSize: "12px",
            padding: "8px 18px",
            borderRadius: "var(--radius-sm)",
            opacity: isPendingAction ? 0.5 : undefined,
          }}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn-accent"
          disabled={isPendingAction}
          onClick={handleConfirm}
          style={{
            fontSize: "12px",
            padding: "8px 20px",
            borderRadius: "var(--radius-sm)",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            opacity: isPendingAction ? 0.6 : undefined,
          }}
        >
          {isPendingAction ? (
            <>
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
              Queuing…
            </>
          ) : (
            <>
              <RocketIcon />
              Confirm &amp; Deploy
            </>
          )}
        </button>
      </div>
    </div>
  );
}
