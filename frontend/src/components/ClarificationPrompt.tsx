import { useState } from "react";
import type { UIFrame } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export default function ClarificationPrompt({ frame, onAction }: Props) {
  const question = (frame.props.question as string) ?? "";
  const options = (frame.props.options as string[]) ?? [];
  const customPlaceholder =
    (frame.props.custom_input_placeholder as string) ?? "Or type a custom answer…";

  const [clickedIdx, setClickedIdx] = useState<number | null>(null);
  const [customText, setCustomText] = useState("");
  const [customSubmitted, setCustomSubmitted] = useState(false);
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const answered = clickedIdx !== null || customSubmitted;

  function handleOptionClick(option: string, i: number) {
    if (answered) return;
    setClickedIdx(i);
    const matchingAction = frame.actions[i];
    if (matchingAction) {
      onAction(frame.instance_id, matchingAction.id, matchingAction.payload);
    } else {
      onAction(frame.instance_id, `option_${i}`, { response: option });
    }
  }

  function handleCustomSubmit() {
    const text = customText.trim();
    if (!text || answered) return;
    setCustomSubmitted(true);
    onAction(frame.instance_id, "custom_answer", { response: text });
  }

  const hasOptions = options.length > 0;
  const hasExtraActions = frame.actions.length > options.length;

  return (
    <div
      className="surface-card overflow-hidden"
      style={{ opacity: answered ? 0.6 : 1, transition: "opacity 0.3s" }}
    >
      {/* Question */}
      <div
        style={{
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div className="flex items-start gap-2.5">
          <span style={{ color: "var(--warning)", fontSize: "12px", marginTop: "2px" }}>?</span>
          <p style={{ fontSize: "13px", lineHeight: "1.65", color: "var(--text-primary)" }}>
            {question}
          </p>
        </div>
      </div>

      {/* MCQ Options */}
      {hasOptions && (
        <div className="flex flex-wrap gap-2" style={{ padding: "12px 20px" }}>
          {options.map((option, i) => {
            const isClicked = clickedIdx === i;
            return (
              <button
                key={i}
                type="button"
                disabled={answered || isPendingAction}
                className="btn-ghost"
                style={
                  isClicked
                    ? { borderColor: "var(--accent)", color: "var(--accent)", background: "var(--accent-glow)" }
                    : answered
                      ? { opacity: 0.4, cursor: "default" }
                      : undefined
                }
                onClick={() => handleOptionClick(option, i)}
              >
                {isClicked && isPendingAction ? (
                  <>
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    {option}
                  </>
                ) : (
                  option
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Extra actions beyond options */}
      {hasExtraActions && (
        <div
          className="flex flex-wrap gap-2"
          style={{
            padding: "12px 20px",
            borderTop: hasOptions ? "1px solid var(--border-subtle)" : "none",
          }}
        >
          {frame.actions.slice(options.length).map((action, i) => {
            const isClicked = clickedIdx === options.length + i;
            return (
              <button
                key={action.id}
                type="button"
                disabled={answered || isPendingAction}
                className="btn-accent"
                style={answered && !isClicked ? { opacity: 0.4, cursor: "default" } : undefined}
                onClick={() => {
                  if (answered) return;
                  setClickedIdx(options.length + i);
                  onAction(frame.instance_id, action.id, action.payload);
                }}
              >
                {isClicked && isPendingAction ? (
                  <>
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    {action.label}
                  </>
                ) : (
                  action.label
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Custom text input — always shown */}
      <div
        style={{
          padding: "10px 20px 14px",
          borderTop: hasOptions || hasExtraActions ? "1px solid var(--border-subtle)" : "none",
        }}
      >
        <div style={{ display: "flex", gap: "8px" }}>
          <input
            type="text"
            placeholder={customPlaceholder}
            value={customText}
            disabled={answered || isPendingAction}
            onChange={(e) => setCustomText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCustomSubmit();
            }}
            style={{
              flex: 1,
              padding: "7px 10px",
              fontSize: "12px",
              fontFamily: "var(--font-body)",
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text-primary)",
              outline: "none",
              opacity: answered ? 0.4 : 1,
            }}
          />
          <button
            type="button"
            className="btn-accent"
            disabled={!customText.trim() || answered || isPendingAction}
            onClick={handleCustomSubmit}
            style={{
              flexShrink: 0,
              opacity: !customText.trim() || answered || isPendingAction ? 0.4 : 1,
            }}
          >
            {customSubmitted && isPendingAction ? (
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : (
              "Send"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
