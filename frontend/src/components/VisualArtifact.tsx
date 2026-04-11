import { useState, useRef, useEffect } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";

interface VisualArtifactData {
  id: string;
  type: string;
  format: string;
  content: string;
  created_at: string;
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export default function VisualArtifact({ frame, onAction }: Props) {
  const artifact = frame.props.artifact as VisualArtifactData | undefined;
  const [expanded, setExpanded] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Auto-resize iframe to fit content
  useEffect(() => {
    if (!iframeRef.current || !artifact?.content) return;
    const iframe = iframeRef.current;
    const doc = iframe.contentDocument;
    if (!doc) return;

    doc.open();
    doc.write(`
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { background: transparent; display: flex; justify-content: center; }
          </style>
        </head>
        <body>${artifact.content}</body>
      </html>
    `);
    doc.close();

    // Resize after content renders
    const resize = () => {
      if (doc.body) {
        iframe.style.height = doc.body.scrollHeight + "px";
      }
    };
    setTimeout(resize, 100);
    setTimeout(resize, 500);
  }, [artifact?.content]);

  if (!artifact) {
    return (
      <div
        className="surface-card"
        style={{ padding: "20px 24px", color: "var(--text-muted)", fontSize: "13px" }}
      >
        No visual artifact generated.
      </div>
    );
  }

  const approveAction = frame.actions.find((a: UIAction) => a.action_type === "approve_visual");
  const regenerateAction = frame.actions.find(
    (a: UIAction) => a.action_type === "regenerate_visual"
  );

  return (
    <div
      className="surface-card overflow-hidden"
      style={{ boxShadow: "0 0 40px rgba(0,212,170,0.04), 0 4px 24px rgba(0,0,0,0.3)" }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid #a855f7",
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
              background: "#a855f7",
              boxShadow: "0 0 8px rgba(168,85,247,0.5)",
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
            Campaign Visual
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              fontSize: "9px",
              fontWeight: 700,
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.08em",
              color: "#a855f7",
              background: "rgba(168,85,247,0.12)",
              border: "1px solid rgba(168,85,247,0.3)",
              borderRadius: "3px",
              padding: "2px 7px",
              textTransform: "uppercase",
            }}
          >
            {artifact.type.replace(/_/g, " ")}
          </span>
          <span
            style={{
              fontSize: "9px",
              fontWeight: 600,
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
              textTransform: "uppercase",
            }}
          >
            {artifact.format}
          </span>
        </div>
      </div>

      {/* Visual preview */}
      <div
        style={{
          padding: "16px",
          background: "var(--bg-surface-1)",
          display: "flex",
          justifyContent: "center",
          maxHeight: expanded ? "none" : "400px",
          overflow: "hidden",
          position: "relative",
          transition: "max-height 0.3s ease",
        }}
      >
        <iframe
          ref={iframeRef}
          title="Campaign Visual Preview"
          sandbox="allow-same-origin"
          style={{
            width: "100%",
            maxWidth: "600px",
            border: "none",
            borderRadius: "8px",
            background: "transparent",
            minHeight: "200px",
          }}
        />

        {!expanded && (
          <div
            style={{
              position: "absolute",
              bottom: 0,
              left: 0,
              right: 0,
              height: "60px",
              background: "linear-gradient(transparent, var(--bg-surface-1))",
              pointerEvents: "none",
            }}
          />
        )}
      </div>

      {/* Expand/collapse toggle */}
      <div style={{ textAlign: "center", padding: "4px 0" }}>
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: "11px",
            color: "#a855f7",
            fontFamily: "var(--font-mono)",
            padding: "4px 12px",
          }}
        >
          {expanded ? "▲ Collapse" : "▼ Expand full preview"}
        </button>
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
        {regenerateAction && (
          <button
            type="button"
            className="btn-ghost"
            onClick={() =>
              onAction(frame.instance_id, regenerateAction.id, regenerateAction.payload)
            }
          >
            Regenerate
          </button>
        )}
        {approveAction && (
          <button
            type="button"
            className="btn-accent"
            onClick={() => onAction(frame.instance_id, approveAction.id, approveAction.payload)}
            style={{ marginLeft: "auto" }}
          >
            Approve Visual
          </button>
        )}
      </div>
    </div>
  );
}
