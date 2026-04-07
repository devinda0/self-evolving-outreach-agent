import type { UIFrame } from "../../store/campaignStore";

interface StubComponentProps {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export default function StubComponent({ frame, onAction }: StubComponentProps) {
  return (
    <div className="surface-card overflow-hidden">
      <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--text-muted)" }} />
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--text-muted)" }}>
          {frame.component ?? "Unknown Component"}
        </span>
      </div>

      {frame.props && Object.keys(frame.props).length > 0 && (
        <pre style={{
          margin: 0,
          padding: "12px 16px",
          maxHeight: "160px",
          overflow: "auto",
          fontFamily: "var(--font-mono)",
          fontSize: "11px",
          lineHeight: "1.6",
          color: "var(--text-secondary)",
          background: "var(--surface-1)",
          borderBottom: frame.actions.length > 0 ? "1px solid var(--border-subtle)" : "none",
        }}>
          {JSON.stringify(frame.props, null, 2)}
        </pre>
      )}

      {frame.actions.length > 0 && (
        <div className="flex flex-wrap gap-2" style={{ padding: "12px 16px" }}>
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
