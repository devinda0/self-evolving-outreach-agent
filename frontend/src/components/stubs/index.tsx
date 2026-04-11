import StubComponent from "./StubComponent";
import type { UIFrame } from "../../store/campaignStore";

// Real implementations
export { default as BriefingCard } from "../BriefingCard";
export { default as ResearchProgress } from "../ResearchProgress";
export { default as ClarificationPrompt } from "../ClarificationPrompt";
export { default as SegmentSelector } from "../SegmentSelector";
export { default as ProspectPicker } from "../ProspectPicker";
export { default as VariantGrid } from "../VariantGrid";
export { default as VisualArtifact } from "../VisualArtifact";
export { default as ChannelSelector } from "../ChannelSelector";
export { default as DeploymentConfirm } from "../DeploymentConfirm";
export { default as DeliveryStatusCard } from "../DeliveryStatusCard";
export { default as ABResults } from "../ABResults";
export { default as CycleSummary } from "../CycleSummary";
export { default as FeedbackPrompt } from "../FeedbackPrompt";
export { default as ManualFeedbackInput } from "../ManualFeedbackInput";
export { default as QuarantineViewer } from "../QuarantineViewer";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export function ErrorCard(props: Props) {
  return <StubComponent {...props} />;
}
