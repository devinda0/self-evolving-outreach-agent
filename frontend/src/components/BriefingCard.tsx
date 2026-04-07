import { useState } from "react";
import type { UIFrame } from "../store/campaignStore";

interface Finding {
  claim: string;
  signal_type: string;
  confidence: number;
  actionable_implication: string;
}

interface BriefingProps {
  executive_summary: string;
  top_findings: Finding[];
  content_angles: string[];
  gaps: string[];
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 rounded-full bg-gray-700">
        <div
          className="h-1.5 rounded-full bg-indigo-400 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-400">{pct}%</span>
    </div>
  );
}

const SIGNAL_COLORS: Record<string, string> = {
  competitor: "bg-red-500/20 text-red-300",
  audience: "bg-blue-500/20 text-blue-300",
  channel: "bg-green-500/20 text-green-300",
  market: "bg-yellow-500/20 text-yellow-300",
};

function SignalBadge({ type }: { type: string }) {
  const colors = SIGNAL_COLORS[type] ?? "bg-gray-500/20 text-gray-300";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${colors}`}>
      {type}
    </span>
  );
}

export default function BriefingCard({ frame, onAction }: Props) {
  const briefing = (frame.props.briefing ?? frame.props) as BriefingProps;
  const findingCount = (frame.props.finding_count as number) ?? briefing.top_findings?.length ?? 0;
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const {
    executive_summary = "",
    top_findings = [],
    content_angles = [],
    gaps = [],
  } = briefing;

  return (
    <div className="rounded-xl bg-gray-900 text-gray-100 shadow-lg">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-700 px-5 py-3">
        <h3 className="text-sm font-semibold tracking-wide">
          Intelligence Briefing
          {findingCount > 0 && (
            <span className="ml-2 text-xs font-normal text-gray-400">
              · {findingCount} finding{findingCount !== 1 ? "s" : ""}
            </span>
          )}
        </h3>
      </div>

      <div className="space-y-4 px-5 py-4">
        {/* Executive summary */}
        {executive_summary && (
          <p className="text-sm leading-relaxed text-gray-300">{executive_summary}</p>
        )}

        {/* Top findings */}
        {top_findings.length > 0 && (
          <div className="space-y-1">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
              Top Findings
            </h4>
            <div className="space-y-1">
              {top_findings.map((f, i) => {
                const isExpanded = expandedIdx === i;
                return (
                  <button
                    key={i}
                    type="button"
                    className="w-full rounded-lg px-3 py-2 text-left hover:bg-gray-800 transition-colors"
                    onClick={() => setExpandedIdx(isExpanded ? null : i)}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <SignalBadge type={f.signal_type} />
                        <span className="truncate text-sm">{f.claim}</span>
                      </div>
                      <ConfidenceBar value={f.confidence} />
                    </div>
                    {isExpanded && f.actionable_implication && (
                      <p className="mt-2 text-xs leading-relaxed text-gray-400 pl-1">
                        {f.actionable_implication}
                      </p>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Content angles */}
        {content_angles.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
              Content Angles
            </h4>
            <div className="flex flex-wrap gap-2">
              {content_angles.map((angle, i) => (
                <span
                  key={i}
                  className="rounded-full bg-indigo-500/20 px-3 py-1 text-xs text-indigo-300"
                >
                  {angle}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Research gaps */}
        {gaps.length > 0 && (
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-gray-500">
              Research Gaps
            </h4>
            <ul className="space-y-1 text-xs text-gray-500">
              {gaps.map((gap, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span className="mt-0.5 text-gray-600">•</span>
                  {gap}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Action buttons */}
      {frame.actions.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-gray-700 px-5 py-3">
          {frame.actions.map((action) => (
            <button
              key={action.id}
              type="button"
              className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 transition-colors"
              onClick={() => onAction(frame.instance_id, action.id, action.payload)}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
