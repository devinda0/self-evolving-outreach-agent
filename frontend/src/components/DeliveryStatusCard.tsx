import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface ChannelDelivery {
  channel: string;
  sent: number;
  failed: number;
  failed_recipients?: string[];
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

function CheckCircleIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  );
}

function AlertTriangleIcon() {
  return (
    <svg
      width="18"
      height="18"
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

export default function DeliveryStatusCard({ frame, onAction }: Props) {
  const totalSent = (frame.props.total_sent as number) ?? 0;
  const failed = (frame.props.failed as number) ?? 0;
  const breakdown = (frame.props.breakdown as ChannelDelivery[]) ?? [];
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const allSuccess = failed === 0;

  // Collect all failed recipient IDs for retry
  const allFailedRecipients = breakdown.flatMap(
    (ch) => ch.failed_recipients ?? [],
  );

  const retryAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "retry_failed" || a.id === "retry-failed",
  );
  const viewResultsAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "view_results" || a.id === "view-results",
  );
  const nextCycleAction = frame.actions.find(
    (a: UIAction) =>
      a.action_type === "run_next_cycle" || a.id === "run-next-cycle",
  );

  function handleRetry() {
    if (retryAction) {
      onAction(frame.instance_id, retryAction.id, {
        ...retryAction.payload,
        action: "retry_failed",
        failed_ids: allFailedRecipients,
      });
    } else {
      onAction(frame.instance_id, "retry_failed", {
        action: "retry_failed",
        failed_ids: allFailedRecipients,
      });
    }
  }

  function handleViewResults() {
    if (viewResultsAction) {
      onAction(frame.instance_id, viewResultsAction.id, {
        ...viewResultsAction.payload,
        action: "view_results",
      });
    } else {
      onAction(frame.instance_id, "view_results", {
        action: "view_results",
      });
    }
  }

  function handleNextCycle() {
    if (nextCycleAction) {
      onAction(frame.instance_id, nextCycleAction.id, {
        ...nextCycleAction.payload,
        action: "run_next_cycle",
      });
    } else {
      onAction(frame.instance_id, "run_next_cycle", {
        action: "run_next_cycle",
      });
    }
  }

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
          borderTop: `2px solid ${allSuccess ? "var(--success)" : "var(--signal-market)"}`,
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
              background: allSuccess
                ? "var(--success)"
                : "var(--signal-market)",
              boxShadow: allSuccess
                ? "0 0 8px rgba(81,207,102,0.6)"
                : "0 0 8px rgba(255,212,59,0.6)",
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
            Delivery Status
          </span>
        </div>
        <span
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            color: allSuccess ? "var(--success)" : "var(--signal-market)",
          }}
        >
          {totalSent} sent · {failed} failed
        </span>
      </div>

      {/* Status banner */}
      <div
        style={{
          margin: "16px 20px 12px",
          padding: "12px 16px",
          borderRadius: "var(--radius-sm)",
          background: allSuccess
            ? "rgba(81,207,102,0.08)"
            : "rgba(255,212,59,0.08)",
          border: `1px solid ${allSuccess ? "rgba(81,207,102,0.3)" : "rgba(255,212,59,0.25)"}`,
          display: "flex",
          alignItems: "center",
          gap: "10px",
        }}
      >
        <span
          style={{
            color: allSuccess ? "var(--success)" : "var(--signal-market)",
            flexShrink: 0,
          }}
        >
          {allSuccess ? <CheckCircleIcon /> : <AlertTriangleIcon />}
        </span>
        <span
          style={{
            fontSize: "12px",
            lineHeight: "1.5",
            color: allSuccess ? "var(--success)" : "var(--signal-market)",
            fontWeight: 600,
          }}
        >
          {allSuccess
            ? `All ${totalSent} messages delivered successfully.`
            : `${totalSent} delivered, ${failed} failed. Review failures below.`}
        </span>
      </div>

      {/* Channel breakdown */}
      {breakdown.length > 0 && (
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
              Breakdown by Channel
            </span>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Channel", "Sent", "Failed"].map((h) => (
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
              {breakdown.map((ch) => {
                const style =
                  CHANNEL_STYLES[ch.channel.toLowerCase()] ?? {
                    color: "var(--text-muted)",
                    label: ch.channel,
                  };
                return (
                  <tr key={ch.channel}>
                    <td
                      style={{
                        padding: "8px 14px",
                        fontSize: "12px",
                        fontWeight: 600,
                        color: style.color,
                      }}
                    >
                      {style.label}
                    </td>
                    <td
                      style={{
                        padding: "8px 14px",
                        fontSize: "12px",
                        fontFamily: "var(--font-mono)",
                        color: "var(--success)",
                      }}
                    >
                      {ch.sent}
                    </td>
                    <td
                      style={{
                        padding: "8px 14px",
                        fontSize: "12px",
                        fontFamily: "var(--font-mono)",
                        color:
                          ch.failed > 0
                            ? "var(--signal-market)"
                            : "var(--text-muted)",
                      }}
                    >
                      {ch.failed}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Failed recipients per channel */}
          {breakdown
            .filter(
              (ch) =>
                ch.failed > 0 &&
                ch.failed_recipients &&
                ch.failed_recipients.length > 0,
            )
            .map((ch) => {
              const style =
                CHANNEL_STYLES[ch.channel.toLowerCase()] ?? {
                  color: "var(--text-muted)",
                  label: ch.channel,
                };
              return (
                <div
                  key={`${ch.channel}-failed`}
                  style={{
                    padding: "8px 14px",
                    borderTop: "1px solid var(--border-subtle)",
                  }}
                >
                  <span
                    style={{
                      fontSize: "9px",
                      fontWeight: 700,
                      fontFamily: "var(--font-mono)",
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      color: "var(--signal-market)",
                      marginBottom: "6px",
                      display: "block",
                    }}
                  >
                    Failed — {style.label}
                  </span>
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "4px",
                    }}
                  >
                    {ch.failed_recipients!.map((name) => (
                      <span
                        key={name}
                        style={{
                          fontSize: "10px",
                          fontFamily: "var(--font-mono)",
                          color: "var(--signal-market)",
                          background: "rgba(255,212,59,0.1)",
                          border: "1px solid rgba(255,212,59,0.25)",
                          borderRadius: "3px",
                          padding: "2px 8px",
                        }}
                      >
                        {name}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
        </div>
      )}

      {/* Retry failed button (only when failures exist) */}
      {failed > 0 && allFailedRecipients.length > 0 && (
        <div
          style={{
            padding: "0 20px 8px",
            display: "flex",
            justifyContent: "flex-start",
          }}
        >
          <button
            type="button"
            disabled={isPendingAction}
            onClick={handleRetry}
            style={{
              fontSize: "11px",
              fontWeight: 600,
              fontFamily: "var(--font-mono)",
              color: "var(--signal-market)",
              background: "rgba(255,212,59,0.1)",
              border: "1px solid rgba(255,212,59,0.3)",
              borderRadius: "var(--radius-sm)",
              padding: "6px 14px",
              cursor: isPendingAction ? "default" : "pointer",
              transition: "all 0.15s ease",
              opacity: isPendingAction ? 0.5 : undefined,
            }}
          >
            Retry Failed ({allFailedRecipients.length})
          </button>
        </div>
      )}

      {/* Footer action buttons */}
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
          onClick={handleViewResults}
          style={{
            fontSize: "12px",
            padding: "8px 18px",
            borderRadius: "var(--radius-sm)",
            opacity: isPendingAction ? 0.5 : undefined,
          }}
        >
          View Results Later
        </button>
        <button
          type="button"
          className="btn-accent"
          disabled={isPendingAction}
          onClick={handleNextCycle}
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
