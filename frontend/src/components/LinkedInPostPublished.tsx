import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

function CheckCircleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  );
}

function MessageSquareIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

export default function LinkedInPostPublished({ frame, onAction }: Props) {
  const postId = (frame.props.post_id as string) ?? "";
  const publishedAt = (frame.props.published_at as string) ?? "";
  const caption = (frame.props.caption as string) ?? "";
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const commentsAction = frame.actions.find(
    (a: UIAction) => a.action_type === "monitor_linkedin_comments" || a.id === "monitor_linkedin_comments",
  );

  function handleCheckComments() {
    const id = commentsAction?.id ?? "monitor_linkedin_comments";
    onAction(frame.instance_id, id, { ...(commentsAction?.payload ?? {}), post_id: postId });
  }

  const formattedDate = publishedAt
    ? new Date(publishedAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : null;

  return (
    <div
      className="surface-card overflow-hidden"
      style={{ boxShadow: "0 0 40px rgba(10,102,194,0.08), 0 4px 24px rgba(0,0,0,0.3)" }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid #22c55e",
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          gap: "10px",
        }}
      >
        <span style={{ color: "#22c55e" }}><CheckCircleIcon /></span>
        <span style={{ fontFamily: "var(--font-display)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
          Post Published Successfully
        </span>
      </div>

      {/* Details */}
      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: "10px" }}>
        {postId && (
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontSize: "10px", fontWeight: 700, fontFamily: "var(--font-mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-muted)", minWidth: "80px" }}>
              Post ID
            </span>
            <span style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--text-secondary)", background: "var(--bg-surface-2)", border: "1px solid var(--border-subtle)", borderRadius: "3px", padding: "2px 8px" }}>
              {postId}
            </span>
          </div>
        )}
        {formattedDate && (
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontSize: "10px", fontWeight: 700, fontFamily: "var(--font-mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-muted)", minWidth: "80px" }}>
              Published
            </span>
            <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{formattedDate}</span>
          </div>
        )}
      </div>

      {/* Caption snippet */}
      {caption && (
        <div style={{ padding: "0 20px 16px" }}>
          <div style={{ fontSize: "10px", fontWeight: 700, fontFamily: "var(--font-mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: "6px" }}>
            Caption
          </div>
          <div
            style={{
              background: "var(--bg-surface-2)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              padding: "10px 12px",
              fontSize: "12px",
              lineHeight: "1.6",
              color: "var(--text-secondary)",
              whiteSpace: "pre-wrap",
              maxHeight: "100px",
              overflowY: "auto",
            }}
          >
            {caption}
          </div>
        </div>
      )}

      {/* Action */}
      <div style={{ padding: "10px 20px 16px", display: "flex", justifyContent: "flex-end", borderTop: "1px solid var(--border-subtle)" }}>
        <button
          type="button"
          className="btn-accent"
          disabled={isPendingAction}
          onClick={handleCheckComments}
          style={{ fontSize: "12px", padding: "8px 20px", borderRadius: "var(--radius-sm)", display: "flex", alignItems: "center", gap: "6px", opacity: isPendingAction ? 0.6 : undefined }}
        >
          {isPendingAction ? (
            <><span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" /> Loading…</>
          ) : (
            <><MessageSquareIcon /> Check Comments &amp; Replies</>
          )}
        </button>
      </div>
    </div>
  );
}
