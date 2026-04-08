import { useState } from "react";
import type { UIFrame } from "../store/campaignStore";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export default function ClarificationPrompt({ frame, onAction }: Props) {
  const question = (frame.props.question as string) ?? "";
  const options = (frame.props.options as string[]) ?? [];
  const [clickedIdx, setClickedIdx] = useState<number | null>(null);
  const answered = clickedIdx !== null;

  function handleOptionClick(option: string, i: number) {
    if (answered) return;
    setClickedIdx(i);
    const matchingAction = frame.actions[i];
    if (matchingAction) {
      onAction(frame.instance_id, matchingAction.id, matchingAction.payload);
    } else {
      // Fallback: use 'response' key so handleAction treats it as a user message
      onAction(frame.instance_id, `option_${i}`, { response: option });
    }
  }

  return (
    <div className="surface-card overflow-hidden" style={{ opacity: answered ? 0.6 : 1, transition: "opacity 0.3s" }}>
      {/* Question */}
      <div style={{ padding: "14px 20px", borderBottom: options.length > 0 || frame.actions.length > 0 ? "1px solid var(--border-subtle)" : "none" }}>
        <div className="flex items-start gap-2.5">
          <span style={{ color: "var(--warning)", fontSize: "12px", marginTop: "2px" }}>?</span>
          <p style={{ fontSize: "13px", lineHeight: "1.65", color: "var(--text-primary)" }}>
            {question}
          </p>
        </div>
      </div>

      {/* Options */}
      {options.length > 0 && (
        <div className="flex flex-wrap gap-2" style={{ padding: "12px 20px" }}>
          {options.map((option, i) => (
            <button
              key={i}
              type="button"
              disabled={answered}
              className="btn-ghost"
              style={
                clickedIdx === i
                  ? { borderColor: "var(--accent)", color: "var(--accent)", background: "var(--accent-glow)" }
                  : answered
                    ? { opacity: 0.4, cursor: "default" }
                    : undefined
              }
              onClick={() => handleOptionClick(option, i)}
            >
              {option}
            </button>
          ))}
        </div>
      )}

      {/* Extra actions beyond options */}
      {frame.actions.length > options.length && (
        <div className="flex flex-wrap gap-2" style={{ padding: "12px 20px", borderTop: options.length > 0 ? "1px solid var(--border-subtle)" : "none" }}>
          {frame.actions.slice(options.length).map((action, i) => (
            <button
              key={action.id}
              type="button"
              disabled={answered}
              className="btn-accent"
              style={answered ? { opacity: 0.4, cursor: "default" } : undefined}
              onClick={() => {
                if (answered) return;
                setClickedIdx(options.length + i);
                onAction(frame.instance_id, action.id, action.payload);
              }}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
