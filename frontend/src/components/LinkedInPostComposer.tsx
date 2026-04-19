import { useState, useRef, useEffect } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

function LinkedInIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M16 8a6 6 0 016 6v7h-4v-7a2 2 0 00-2-2 2 2 0 00-2 2v7h-4v-7a6 6 0 016-6zM2 9h4v12H2z" />
      <circle cx="4" cy="4" r="2" />
    </svg>
  );
}

function PencilIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
      <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  );
}

export default function LinkedInPostComposer({ frame, onAction }: Props) {
  const html = (frame.props.html as string) ?? "";
  const initialCaption = (frame.props.caption as string) ?? "";
  const [caption, setCaption] = useState(initialCaption);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const publishAction = frame.actions.find(
    (a: UIAction) => a.action_type === "publish_linkedin_post" || a.id === "publish_linkedin_post",
  );
  const refineAction = frame.actions.find(
    (a: UIAction) => a.action_type === "refine_linkedin_post" || a.id === "refine_linkedin_post",
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

  function handlePublish() {
    const id = publishAction?.id ?? "publish_linkedin_post";
    onAction(frame.instance_id, id, { ...(publishAction?.payload ?? {}), caption });
  }

  function handleRefine() {
    const id = refineAction?.id ?? "refine_linkedin_post";
    onAction(frame.instance_id, id, { ...(refineAction?.payload ?? {}), caption });
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
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#0a66c2", boxShadow: "0 0 8px rgba(10,102,194,0.6)", flexShrink: 0 }} />
          <span style={{ fontFamily: "var(--font-display)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
            LinkedIn Post Composer
          </span>
        </div>
        <span style={{ fontSize: "9px", fontWeight: 700, fontFamily: "var(--font-mono)", letterSpacing: "0.08em", color: "#0a66c2", background: "rgba(10,102,194,0.12)", border: "1px solid rgba(10,102,194,0.3)", borderRadius: "3px", padding: "2px 7px", textTransform: "uppercase" }}>
          Feed Post
        </span>
      </div>

      {/* Flyer preview */}
      <div style={{ padding: "16px", background: "var(--bg-surface-1)", display: "flex", justifyContent: "center" }}>
        <iframe
          ref={iframeRef}
          title="LinkedIn Flyer Preview"
          sandbox="allow-same-origin"
          style={{ width: "100%", maxWidth: "600px", border: "none", borderRadius: "8px", background: "transparent", minHeight: "200px" }}
        />
      </div>

      {/* Caption editor */}
      <div style={{ padding: "14px 20px" }}>
        <label style={{ display: "block", fontSize: "10px", fontWeight: 700, fontFamily: "var(--font-mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: "8px" }}>
          Post Caption
        </label>
        <textarea
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          rows={5}
          style={{
            width: "100%",
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-sm)",
            color: "var(--text-primary)",
            fontSize: "13px",
            lineHeight: "1.6",
            padding: "10px 12px",
            resize: "vertical",
            fontFamily: "inherit",
            outline: "none",
          }}
          placeholder="Edit your caption here…"
        />
        <div style={{ marginTop: "4px", textAlign: "right", fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
          {caption.length} chars
        </div>
      </div>

      {/* Actions */}
      <div style={{ padding: "10px 20px 16px", display: "flex", justifyContent: "flex-end", gap: "10px", borderTop: "1px solid var(--border-subtle)" }}>
        <button
          type="button"
          className="btn-ghost"
          disabled={isPendingAction}
          onClick={handleRefine}
          style={{ fontSize: "12px", padding: "8px 16px", borderRadius: "var(--radius-sm)", display: "flex", alignItems: "center", gap: "6px", opacity: isPendingAction ? 0.5 : undefined }}
        >
          <PencilIcon />
          Refine flyer / caption
        </button>
        <button
          type="button"
          className="btn-accent"
          disabled={isPendingAction}
          onClick={handlePublish}
          style={{ fontSize: "12px", padding: "8px 20px", borderRadius: "var(--radius-sm)", background: "#0a66c2", display: "flex", alignItems: "center", gap: "6px", opacity: isPendingAction ? 0.6 : undefined }}
        >
          {isPendingAction ? (
            <><span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" /> Posting…</>
          ) : (
            <><LinkedInIcon /> Post to LinkedIn</>
          )}
        </button>
      </div>
    </div>
  );
}
