import StubComponent from "./StubComponent";
import type { UIFrame } from "../../store/campaignStore";

// Real implementations
export { default as BriefingCard } from "../BriefingCard";
export { default as ResearchProgress } from "../ResearchProgress";
export { default as ClarificationPrompt } from "../ClarificationPrompt";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export function ProspectPicker(props: Props) {
  return <StubComponent {...props} />;
}

export function VariantGrid(props: Props) {
  return <StubComponent {...props} />;
}

export function ChannelSelector(props: Props) {
  return <StubComponent {...props} />;
}

export function DeploymentConfirm(props: Props) {
  return <StubComponent {...props} />;
}

export function ABResults(props: Props) {
  return <StubComponent {...props} />;
}

export function CycleSummary(props: Props) {
  return <StubComponent {...props} />;
}

export function ErrorCard(props: Props) {
  return <StubComponent {...props} />;
}
