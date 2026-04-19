import { useEffect, useRef } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

function ShieldIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

function ArrowLeftIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  );
}

export default function LinkedInPostConfirm({ frame, onAction }: Props) {
  const html = (frame.props.html as string) ?? "";
  const caption =
    (frame.props.caption as string) ??
    (frame.props.caption_preview as string) ??
    "";
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const confirmAction = frame.actions.find(
    (a: UIAction) => a.action_type === "confirm_linkedin_post" || a.id === "confirm_linkedin_post",
  );
  const cancelAction = frame.actions.find(
    (a: UIAction) => a.action_type === "cancel_linkedin_post" || a.id === "cancel_linkedin_post",
  );

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe || !html) return;
    const doc = iframe.contentDocument;
    if (!doc) return;
    doc.open();
    doc.write(`<!DOCTYPE html><html><head>
      <meta charset="utf-8"/>
      <style>*{margin:0;padding:0;box-sizing:border-box;}body{background:transparent;display:flex;justify-content:center;}</style>
    </head><body>${html}</body></html>`);
    doc.close();
    const resize = () => {
      if (doc.body) iframe.style.height = doc.body.scrollHeight + "px";
    };
    setTimeout(resize, 100);
    setTimeout(resize, 600);
  }, [html]);

  function handleConfirm() {
    const id = confirmAction?.id ?? "confirm_linkedin_post";
    onAction(frame.instance_id, id, { ...(confirmAction?.payload ?? {}), action: "confirm_linkedin_post" });
  }

  function handleCancel() {
    const id = cancelAction?.id ?? "cancel_linkedin_post";
    onAction(frame.instance_id, id, { ...(cancelAction?.payload ?? {}), action: "cancel_linkedin_post" });
  }

  return (
    <div
      className="surface-card overflow-hidden"
      style={{ boxShadow: "0 0 40px rgba(10,102,194,0.08), 0 4px 24px rgba(0,0,0,0.3)" }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid #0a66c2",
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          gap: "10px",
        }}
      >
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#0a66c2", boxShadow: "0 0 8px rgba(10,102,194,0.6)", flexShrink: 0 }} />
        <span style={{ fontFamily: "var(--font-display)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
          Confirm LinkedIn Post
        </span>
      </div>

      {/* Flyer preview */}
      {html && (
        <div style={{ padding: "16px", background: "var(--bg-surface-1)", display: "flex", justifyContent: "center", borderBottom: "1px solid var(--border-subtle)" }}>
          <iframe
            ref={iframeRef}
            title="LinkedIn Flyer Confirmation Preview"
            sandbox="allow-same-origin"
            style={{ width: "100%", maxWidth: "600px", border: "none", borderRadius: "8px", background: "transparent", minHeight: "200px" }}
          />
        </div>
      )}

      {/* Caption preview */}
      <div style={{ padding: "16px 20px" }}>
        <div style={{ fontSize: "10px", fontWeight: 700, fontFamily: "var(--font-mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: "8px" }}>
          Caption Preview
        </div>
        <div
          style={{
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-sm)",
            padding: "12px 14px",
            fontSize: "13px",
            lineHeight: "1.65",
            color: "var(--text-secondary)",
            whiteSpace: "pre-wrap",
            maxHeight: "160px",
            overflowY: "auto",
          }}
        >
          {caption || <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>No caption</span>}
        </div>
      </div>

      {/* Warning */}
      <div
        style={{
          margin: "0 20px 16px",
          padding: "10px 14px",
          borderRadius: "var(--radius-sm)",
          background: "rgba(10,102,194,0.08)",
          border: "1px solid rgba(10,102,194,0.25)",
          display: "flex",
          alignItems: "center",
          gap: "10px",
        }}
      >
        <span style={{ color: "#0a66c2", flexShrink: 0 }}><ShieldIcon /></span>
        <span style={{ fontSize: "11.5px", color: "#0a66c2", lineHeight: "1.5" }}>
          This will publish a public post to your LinkedIn feed.
        </span>
      </div>

      {/* Buttons */}
      <div style={{ padding: "10px 20px 16px", display: "flex", justifyContent: "flex-end", gap: "10px", borderTop: "1px solid var(--border-subtle)" }}>
        <button
          type="button"
          className="btn-ghost"
          disabled={isPendingAction}
          onClick={handleCancel}
          style={{ fontSize: "12px", padding: "8px 16px", borderRadius: "var(--radius-sm)", display: "flex", alignItems: "center", gap: "6px", opacity: isPendingAction ? 0.5 : undefined }}
        >
          <ArrowLeftIcon />
          Go Back &amp; Edit
        </button>
        <button
          type="button"
          disabled={isPendingAction}
          onClick={handleConfirm}
          style={{
            fontSize: "12px",
            padding: "8px 20px",
            borderRadius: "var(--radius-sm)",
            background: "#0a66c2",
            color: "#fff",
            border: "none",
            cursor: isPendingAction ? "not-allowed" : "pointer",
            fontWeight: 600,
            opacity: isPendingAction ? 0.6 : 1,
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          {isPendingAction ? (
            <><span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" /> Publishing…</>
          ) : (
            "Confirm & Publish"
          )}
        </button>
      </div>
    </div>
  );
}
