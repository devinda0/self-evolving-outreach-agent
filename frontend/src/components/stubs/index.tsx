import StubComponent from "./StubComponent";
import type { UIFrame } from "../../store/campaignStore";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export function BriefingCard(props: Props) {
  return <StubComponent {...props} />;
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

export function ResearchProgress(props: Props) {
  return <StubComponent {...props} />;
}

export function ClarificationPrompt(props: Props) {
  return <StubComponent {...props} />;
}

export function ErrorCard(props: Props) {
  return <StubComponent {...props} />;
}
