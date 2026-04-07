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
        <pre className="rounded bg-gray-100 p-3 text-xs text-gray-600">
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
      <div className="my-2 max-w-2xl">
        <UIComponentDispatcher frame={message.uiComponent} onAction={onAction} />
      </div>
    );
  }

  return (
    <div className={`my-2 flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-xl rounded-lg px-4 py-2 text-sm whitespace-pre-wrap ${
          isUser
            ? "bg-indigo-600 text-white"
            : "bg-gray-100 text-gray-900"
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}
