import { useState } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Comment {
  comment_id: string;
  author: string;
  text: string;
  created_at?: string;
  suggested_reply?: string;
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

function RefreshIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

function CommentCard({ comment, postId, instanceId, onAction, isPendingAction }: {
  comment: Comment;
  postId: string;
  instanceId: string;
  onAction: Props["onAction"];
  isPendingAction: boolean;
}) {
  const [reply, setReply] = useState(comment.suggested_reply ?? "");
  const [sent, setSent] = useState(false);

  function handleSend() {
    if (!reply.trim() || sent) return;
    onAction(instanceId, "send_comment_reply", {
      post_id: postId,
      comment_id: comment.comment_id,
      reply_text: reply,
    });
    setSent(true);
  }

  const formattedDate = comment.created_at
    ? new Date(comment.created_at).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })
    : null;

  return (
    <div
      style={{
        background: "var(--bg-surface-2)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-sm)",
        overflow: "hidden",
      }}
    >
      {/* Comment header */}
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-primary)" }}>
          {comment.author || "LinkedIn User"}
        </span>
        {formattedDate && (
          <span style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
            {formattedDate}
          </span>
        )}
      </div>

      {/* Comment text */}
      <div style={{ padding: "10px 14px", fontSize: "12px", lineHeight: "1.6", color: "var(--text-secondary)" }}>
        {comment.text}
      </div>

      {/* Reply area */}
      <div style={{ padding: "10px 14px", borderTop: "1px solid var(--border-subtle)", background: "var(--bg-surface-3)" }}>
        <div style={{ fontSize: "9px", fontWeight: 700, fontFamily: "var(--font-mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--accent)", marginBottom: "6px" }}>
          AI Suggested Reply
        </div>
        {sent ? (
          <div style={{ fontSize: "12px", color: "#22c55e", fontWeight: 500 }}>✓ Reply sent</div>
        ) : (
          <div style={{ display: "flex", gap: "8px", alignItems: "flex-start" }}>
            <textarea
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              rows={2}
              style={{
                flex: 1,
                background: "var(--bg-surface-1)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-primary)",
                fontSize: "12px",
                lineHeight: "1.5",
                padding: "6px 10px",
                resize: "vertical",
                fontFamily: "inherit",
                outline: "none",
              }}
              placeholder="Edit reply before sending…"
            />
            <button
              type="button"
              className="btn-accent"
              disabled={isPendingAction || !reply.trim()}
              onClick={handleSend}
              style={{ fontSize: "11px", padding: "6px 12px", borderRadius: "var(--radius-sm)", display: "flex", alignItems: "center", gap: "5px", flexShrink: 0, opacity: (isPendingAction || !reply.trim()) ? 0.5 : undefined }}
            >
              <SendIcon />
              Send
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function LinkedInCommentReview({ frame, onAction }: Props) {
  const postId = (frame.props.post_id as string) ?? "";
  const comments = (frame.props.comments as Comment[]) ?? [];
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const refreshAction = frame.actions.find(
    (a: UIAction) => a.action_type === "refresh_comments" || a.id === "refresh_comments",
  );

  function handleRefresh() {
    const id = refreshAction?.id ?? "refresh_comments";
    onAction(frame.instance_id, id, { ...(refreshAction?.payload ?? {}), post_id: postId });
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
            Comment Review
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
            {comments.length} comment{comments.length !== 1 ? "s" : ""}
          </span>
          <button
            type="button"
            className="btn-ghost"
            disabled={isPendingAction}
            onClick={handleRefresh}
            style={{ fontSize: "11px", padding: "5px 12px", borderRadius: "var(--radius-sm)", display: "flex", alignItems: "center", gap: "5px", opacity: isPendingAction ? 0.5 : undefined }}
          >
            <RefreshIcon />
            Refresh
          </button>
        </div>
      </div>

      {/* Comment list */}
      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: "12px" }}>
        {comments.length === 0 ? (
          <div style={{ textAlign: "center", padding: "24px 0", fontSize: "13px", color: "var(--text-muted)", fontStyle: "italic" }}>
            No comments yet. Check back later.
          </div>
        ) : (
          comments.map((c) => (
            <CommentCard
              key={c.comment_id}
              comment={c}
              postId={postId}
              instanceId={frame.instance_id}
              onAction={onAction}
              isPendingAction={isPendingAction}
            />
          ))
        )}
      </div>
    </div>
  );
}
