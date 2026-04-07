import type { UIFrame } from "../store/campaignStore";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

export default function ClarificationPrompt({ frame, onAction }: Props) {
  const question = (frame.props.question as string) ?? "";
  const options = (frame.props.options as string[]) ?? [];

  return (
    <div className="rounded-xl bg-gray-900 text-gray-100 shadow-lg">
      <div className="px-5 py-4">
        <p className="text-sm leading-relaxed text-gray-200">{question}</p>
      </div>

      {options.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-gray-700 px-5 py-3">
          {options.map((option, i) => {
            const matchingAction = frame.actions[i];
            return (
              <button
                key={i}
                type="button"
                className="rounded-md border border-gray-600 bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-200 hover:border-indigo-500 hover:bg-gray-700 transition-colors"
                onClick={() => {
                  if (matchingAction) {
                    onAction(frame.instance_id, matchingAction.id, matchingAction.payload);
                  } else {
                    onAction(frame.instance_id, `option_${i}`, { selected: option });
                  }
                }}
              >
                {option}
              </button>
            );
          })}
        </div>
      )}

      {/* Render any extra actions not covered by options */}
      {frame.actions.length > options.length && (
        <div className="flex flex-wrap gap-2 border-t border-gray-700 px-5 py-3">
          {frame.actions.slice(options.length).map((action) => (
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
