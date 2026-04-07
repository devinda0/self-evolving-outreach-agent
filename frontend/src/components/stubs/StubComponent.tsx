import type { UIFrame } from "../../store/campaignStore";

interface StubComponentProps {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export default function StubComponent({ frame, onAction }: StubComponentProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
        {frame.component ?? "Unknown Component"}
      </div>
      {frame.props && Object.keys(frame.props).length > 0 && (
        <pre className="mb-3 max-h-40 overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-700">
          {JSON.stringify(frame.props, null, 2)}
        </pre>
      )}
      {frame.actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
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
