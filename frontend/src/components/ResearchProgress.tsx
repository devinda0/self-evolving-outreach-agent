import type { UIFrame } from "../store/campaignStore";

type ThreadStatus = "running" | "done" | "failed";

interface ThreadInfo {
  type: "competitor" | "audience" | "channel" | "market";
  status: ThreadStatus;
  finding_count: number;
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

const THREAD_META: Record<string, { label: string; color: string; icon: string }> = {
  competitor: { label: "Competitor Intel", color: "var(--signal-competitor)", icon: "⬡" },
  audience:   { label: "Audience Signals", color: "var(--signal-audience)",  icon: "◎" },
  channel:    { label: "Channel Analysis", color: "var(--signal-channel)",   icon: "◈" },
  market:     { label: "Market Context",   color: "var(--signal-market)",    icon: "◇" },
};

function StatusIndicator({ status, color }: { status: ThreadStatus; color: string }) {
  if (status === "running") {
    return (
      <span
        className="inline-block"
        style={{
          width: "14px",
          height: "14px",
          borderRadius: "50%",
          border: `2px solid ${color}`,
          borderTopColor: "transparent",
          animation: "spin-slow 0.8s linear infinite",
        }}
      />
    );
  }
  if (status === "done") {
    return (
      <span className="animate-fade-in" style={{ color: "var(--success)", fontSize: "14px", lineHeight: 1 }}>✓</span>
    );
  }
  return (
    <span style={{ color: "var(--danger)", fontSize: "13px", lineHeight: 1 }}>✗</span>
  );
}

export default function ResearchProgress({ frame, onAction }: Props) {
  const threads = (frame.props.threads ?? []) as ThreadInfo[];
  const anyRunning = threads.some((t) => t.status === "running");

  return (
    <div
      className="surface-card overflow-hidden"
      style={{
        boxShadow: anyRunning ? "0 0 30px rgba(0,212,170,0.06)" : undefined,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "12px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          gap: "8px",
        }}
      >
        {anyRunning && (
          <span
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              background: "var(--accent)",
              display: "inline-block",
              animation: "typing-pulse 1.5s ease-in-out infinite",
            }}
          />
        )}
        <span style={{ fontFamily: "var(--font-display)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)" }}>
          {anyRunning ? "Research in Progress" : "Research Complete"}
        </span>
      </div>

      {/* Thread rows */}
      <div style={{ padding: "4px 0" }}>
        {threads.map((t, i) => {
          const meta = THREAD_META[t.type] ?? { label: t.type, color: "var(--text-muted)", icon: "○" };
          return (
            <div
              key={t.type}
              className="flex items-center justify-between"
              style={{
                padding: "10px 20px",
                borderBottom: i < threads.length - 1 ? "1px solid var(--border-subtle)" : "none",
                animation: `fade-in 0.3s ease-out ${i * 0.08}s both`,
              }}
            >
              <div className="flex items-center gap-3">
                <span style={{ fontSize: "14px", color: meta.color, opacity: 0.8 }}>{meta.icon}</span>
                <span style={{ fontSize: "12.5px", fontWeight: 500, color: "var(--text-primary)" }}>
                  {meta.label}
                </span>
              </div>

              <div className="flex items-center gap-3">
                {t.status === "done" && t.finding_count > 0 && (
                  <span style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                    {t.finding_count} signal{t.finding_count !== 1 ? "s" : ""}
                  </span>
                )}
                {t.status === "failed" && (
                  <button
                    type="button"
                    className="btn-ghost"
                    style={{
                      padding: "3px 8px",
                      fontSize: "10px",
                      color: "var(--danger)",
                      borderColor: "rgba(255,77,106,0.2)",
                    }}
                    onClick={() => onAction(frame.instance_id, `retry_${t.type}`, { thread_type: t.type })}
                  >
                    Retry
                  </button>
                )}
                <StatusIndicator status={t.status} color={meta.color} />
              </div>
            </div>
          );
        })}
      </div>

      {frame.actions.length > 0 && (
        <div className="flex flex-wrap gap-2" style={{ padding: "12px 20px", borderTop: "1px solid var(--border-subtle)" }}>
          {frame.actions.map((action, i) => (
            <button
              key={action.id}
              type="button"
              className={i === 0 ? "btn-accent" : "btn-ghost"}
              onClick={() => onAction(frame.instance_id, action.id, action.payload)}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
