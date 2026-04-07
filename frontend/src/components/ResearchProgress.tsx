import type { UIFrame } from "../store/campaignStore";

type ThreadStatus = "running" | "done" | "failed";

interface ThreadInfo {
  type: "competitor" | "audience" | "channel" | "market";
  status: ThreadStatus;
  finding_count: number;
}

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

const THREAD_LABELS: Record<string, string> = {
  competitor: "Competitor",
  audience: "Audience",
  channel: "Channel",
  market: "Market",
};

const THREAD_ICONS: Record<string, string> = {
  competitor: "🏢",
  audience: "👥",
  channel: "📡",
  market: "📈",
};

function StatusIcon({ status }: { status: ThreadStatus }) {
  switch (status) {
    case "running":
      return (
        <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />
      );
    case "done":
      return <span className="text-green-400">✓</span>;
    case "failed":
      return <span className="text-red-400">✗</span>;
  }
}

export default function ResearchProgress({ frame, onAction }: Props) {
  const threads = (frame.props.threads ?? []) as ThreadInfo[];

  return (
    <div className="rounded-xl bg-gray-900 text-gray-100 shadow-lg">
      <div className="border-b border-gray-700 px-5 py-3">
        <h3 className="text-sm font-semibold tracking-wide">Research in Progress</h3>
      </div>

      <div className="divide-y divide-gray-800 px-5">
        {threads.map((t) => (
          <div key={t.type} className="flex items-center justify-between py-3">
            <div className="flex items-center gap-2.5">
              <span className="text-base">{THREAD_ICONS[t.type] ?? "🔍"}</span>
              <span className="text-sm font-medium">
                {THREAD_LABELS[t.type] ?? t.type}
              </span>
            </div>

            <div className="flex items-center gap-3">
              {t.status === "done" && t.finding_count > 0 && (
                <span className="text-xs text-gray-400">
                  {t.finding_count} finding{t.finding_count !== 1 ? "s" : ""}
                </span>
              )}
              {t.status === "failed" ? (
                <button
                  type="button"
                  className="rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-300 hover:bg-red-500/30 transition-colors"
                  onClick={() =>
                    onAction(frame.instance_id, `retry_${t.type}`, { thread_type: t.type })
                  }
                >
                  Retry
                </button>
              ) : null}
              <StatusIcon status={t.status} />
            </div>
          </div>
        ))}
      </div>

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
