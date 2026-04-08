import type { Message, UIFrame } from "../store/campaignStore";
import {
  BriefingCard,
  ProspectPicker,
  VariantGrid,
  ChannelSelector,
  DeploymentConfirm,
  ABResults,
  CycleSummary,
  ResearchProgress,
  ClarificationPrompt,
  ErrorCard,
} from "./stubs";

// ---------------------------------------------------------------------------
// UIComponentDispatcher
// ---------------------------------------------------------------------------

interface DispatcherProps {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

function UIComponentDispatcher({ frame, onAction }: DispatcherProps) {
  const props = { frame, onAction };

  switch (frame.component) {
    case "BriefingCard":
      return <BriefingCard {...props} />;
    case "ProspectPicker":
      return <ProspectPicker {...props} />;
    case "VariantGrid":
      return <VariantGrid {...props} />;
    case "ChannelSelector":
      return <ChannelSelector {...props} />;
    case "DeploymentConfirm":
      return <DeploymentConfirm {...props} />;
    case "ABResults":
      return <ABResults {...props} />;
    case "CycleSummary":
      return <CycleSummary {...props} />;
    case "ResearchProgress":
      return <ResearchProgress {...props} />;
    case "ClarificationPrompt":
      return <ClarificationPrompt {...props} />;
    case "ErrorCard":
      return <ErrorCard {...props} />;
    default:
      return (
        <pre
          className="overflow-auto"
          style={{
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            padding: "12px",
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          {JSON.stringify(frame, null, 2)}
        </pre>
      );
  }
}

// ---------------------------------------------------------------------------
// MessageRenderer
// ---------------------------------------------------------------------------

interface MessageRendererProps {
  message: Message;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export default function MessageRenderer({ message, onAction }: MessageRendererProps) {
  const isUser = message.role === "user";

  if (message.uiComponent) {
    return (
      <div style={{ padding: "8px 0" }} className="animate-fade-in-up">
        <UIComponentDispatcher frame={message.uiComponent} onAction={onAction} />
      </div>
    );
  }

  return (
    <div
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
      style={{
        padding: "4px 0",
        animation: isUser ? "slide-in-right 0.3s ease-out both" : "slide-in-left 0.3s ease-out both",
      }}
    >
      <div
        className="whitespace-pre-wrap"
        style={{
          maxWidth: isUser ? "75%" : "85%",
          padding: "10px 14px",
          fontSize: "13px",
          lineHeight: "1.6",
          borderRadius: isUser ? "var(--radius-lg) var(--radius-lg) 4px var(--radius-lg)" : "var(--radius-lg) var(--radius-lg) var(--radius-lg) 4px",
          ...(isUser
            ? {
                background: "var(--accent)",
                color: "var(--bg-base)",
                fontWeight: 500,
              }
            : {
                background: "var(--bg-surface-2)",
                color: "var(--text-primary)",
                border: "1px solid var(--border-subtle)",
              }),
        }}
      >
        {message.content}
      </div>
    </div>
  );
}
