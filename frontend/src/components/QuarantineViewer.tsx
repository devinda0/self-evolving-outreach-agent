import type { UIFrame } from "../store/campaignStore";

interface QuarantineEvent {
  provider: string;
  provider_event_id?: string | null;
  provider_message_id?: string | null;
  session_id?: string;
  event_type: string;
  channel?: string;
  quarantine_reason?: string;
  received_at: string;
  dedupe_key?: string;
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

function ShieldIcon() {
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
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const EVENT_TYPE_COLORS: Record<string, string> = {
  open: "var(--signal-audience)",
  click: "var(--accent)",
  reply: "var(--success)",
  bounce: "var(--danger)",
  sent: "var(--text-muted)",
};

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function truncate(str: string | null | undefined, n = 18): string {
  if (!str) return "—";
  return str.length > n ? `${str.slice(0, 8)}…${str.slice(-6)}` : str;
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div
      style={{
        padding: "24px 20px",
        textAlign: "center",
        color: "var(--text-muted)",
      }}
    >
      <p style={{ fontSize: "12px" }}>No quarantined events for this session.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Event row
// ---------------------------------------------------------------------------

function EventRow({ event, odd }: { event: QuarantineEvent; odd: boolean }) {
  const typeColor = EVENT_TYPE_COLORS[event.event_type] ?? "var(--text-secondary)";

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "80px 60px 1fr 1fr 110px",
        gap: "8px",
        alignItems: "center",
        padding: "10px 20px",
        background: odd ? "var(--bg-surface-2)" : "transparent",
        borderBottom: "1px solid var(--border-subtle)",
        fontSize: "12px",
      }}
    >
      {/* Provider */}
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "11px",
          color: "var(--text-secondary)",
          textTransform: "lowercase",
        }}
      >
        {event.provider}
      </span>

      {/* Event type badge */}
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "10px",
          fontWeight: 700,
          color: typeColor,
          background: `${typeColor}18`,
          borderRadius: "4px",
          padding: "2px 6px",
          display: "inline-block",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        {event.event_type}
      </span>

      {/* Provider message ID */}
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "11px",
          color: "var(--text-muted)",
          overflow: "hidden",
          whiteSpace: "nowrap",
          textOverflow: "ellipsis",
        }}
        title={event.provider_message_id ?? ""}
      >
        {truncate(event.provider_message_id)}
      </span>

      {/* Quarantine reason */}
      <span
        style={{
          fontSize: "11px",
          color: "var(--text-muted)",
          fontStyle: "italic",
          overflow: "hidden",
          whiteSpace: "nowrap",
          textOverflow: "ellipsis",
        }}
        title={event.quarantine_reason ?? ""}
      >
        {event.quarantine_reason
          ? event.quarantine_reason.replace(/_/g, " ")
          : "—"}
      </span>

      {/* Received at */}
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "10px",
          color: "var(--text-muted)",
        }}
      >
        {formatDate(event.received_at)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function QuarantineViewer({ frame }: Props) {
  const events = (frame.props.events as QuarantineEvent[]) ?? [];

  return (
    <div
      className="surface-card overflow-hidden animate-fade-in-up"
      style={{ boxShadow: "0 2px 16px rgba(0,0,0,0.25)" }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid var(--signal-market)",
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span
            style={{ color: "var(--signal-market)", display: "flex" }}
          >
            <ShieldIcon />
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
            Quarantine Viewer
          </span>
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "10px",
            color:
              events.length > 0
                ? "var(--signal-market)"
                : "var(--text-muted)",
          }}
        >
          {events.length} event{events.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Description */}
      <div
        style={{
          padding: "10px 20px",
          background: "rgba(255,212,59,0.04)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <p
          style={{
            fontSize: "12px",
            color: "var(--text-muted)",
            lineHeight: "1.5",
          }}
        >
          These events could not be correlated to any deployment record. They
          may result from provider IDs arriving before deployment records are
          persisted, or from test traffic.
        </p>
      </div>

      {/* Table header */}
      {events.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "80px 60px 1fr 1fr 110px",
            gap: "8px",
            padding: "8px 20px",
            borderBottom: "1px solid var(--border-subtle)",
            background: "var(--bg-surface-2)",
          }}
        >
          {["Provider", "Type", "Message ID", "Reason", "Received"].map(
            (col) => (
              <span
                key={col}
                style={{
                  fontSize: "9px",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.07em",
                  color: "var(--text-muted)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {col}
              </span>
            ),
          )}
        </div>
      )}

      {/* Rows */}
      {events.length === 0 ? (
        <EmptyState />
      ) : (
        <div>
          {events.map((event, i) => (
            <EventRow
              key={event.dedupe_key ?? i}
              event={event}
              odd={i % 2 === 0}
            />
          ))}
        </div>
      )}
    </div>
  );
}
