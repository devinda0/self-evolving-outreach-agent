import { useState, useMemo } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Prospect {
  id: string;
  name: string;
  title: string;
  company: string;
  fit_score: number;
  urgency_score: number;
  angle_recommendation: string;
  channel_recommendation: string;
}

type SortKey = "fit_score" | "urgency_score";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

const EMPTY_PROSPECTS: Prospect[] = [];
const EMPTY_SELECTED_IDS: string[] = [];

// ---------- small sub-components ----------

function ScoreBar({ value, color }: { value: number; color: string }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "6px", minWidth: "80px" }}>
      <div
        style={{
          flex: 1,
          height: "3px",
          borderRadius: "2px",
          background: "var(--bg-base)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            borderRadius: "2px",
            background: color,
            boxShadow: `0 0 6px ${color}`,
            transition: "width 0.4s ease-out",
          }}
        />
      </div>
      <span
        style={{
          fontSize: "10px",
          fontFamily: "var(--font-mono)",
          color: "var(--text-muted)",
          minWidth: "28px",
          textAlign: "right",
        }}
      >
        {pct}%
      </span>
    </div>
  );
}

const CHANNEL_STYLES: Record<string, { color: string; bg: string }> = {
  email:    { color: "var(--signal-audience)", bg: "rgba(77,171,247,0.1)" },
  linkedin: { color: "var(--signal-market)",   bg: "rgba(255,212,59,0.1)" },
  twitter:  { color: "#74c0fc",                bg: "rgba(116,192,252,0.1)" },
  sms:      { color: "var(--signal-channel)",  bg: "rgba(81,207,102,0.1)" },
};

function Pill({
  label,
  colorKey,
}: {
  label: string;
  colorKey?: string;
}) {
  const key = (colorKey ?? label).toLowerCase();
  const s = CHANNEL_STYLES[key] ?? {
    color: "var(--text-muted)",
    bg: "var(--bg-elevated)",
  };
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: "9.5px",
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.04em",
        color: s.color,
        background: s.bg,
        border: `1px solid ${s.color}33`,
        borderRadius: "4px",
        padding: "2px 7px",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

// ---------- main component ----------

export default function ProspectPicker({ frame, onAction }: Props) {
  const prospects = (frame.props.prospects as Prospect[] | undefined) ?? EMPTY_PROSPECTS;
  const initialSelected = (frame.props.selected_ids as string[] | undefined) ?? EMPTY_SELECTED_IDS;

  const [selected, setSelected] = useState<Set<string>>(new Set(initialSelected));
  const [titleFilter, setTitleFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("fit_score");
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const deployAction = frame.actions.find(
    (a: UIAction) => a.action_type === "confirm_prospects" || a.id === "confirm_prospects"
  );

  // Derived: filtered + sorted
  const filtered = useMemo(() => {
    const lower = titleFilter.toLowerCase().trim();
    return prospects
      .filter((p) => !lower || p.title.toLowerCase().includes(lower))
      .sort((a, b) => b[sortKey] - a[sortKey]);
  }, [prospects, titleFilter, sortKey]);

  // Sorted by fit_score for "Select Top 10"
  const sortedByFit = useMemo(
    () => [...prospects].sort((a, b) => b.fit_score - a.fit_score),
    [prospects]
  );

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll() {
    setSelected(new Set(filtered.map((p) => p.id)));
  }

  function selectTop10() {
    setSelected(new Set(sortedByFit.slice(0, 10).map((p) => p.id)));
  }

  function clearAll() {
    setSelected(new Set());
  }

  function handleDeploy() {
    const selected_ids = Array.from(selected);
    if (deployAction) {
      onAction(frame.instance_id, deployAction.id, {
        ...deployAction.payload,
        selected_ids,
      });
    } else {
      onAction(frame.instance_id, "confirm_prospects", { selected_ids });
    }
  }

  const selectedCount = selected.size;
  const totalCount = prospects.length;

  return (
    <div
      className="surface-card overflow-hidden"
      style={{ boxShadow: "0 0 40px rgba(0,212,170,0.04), 0 4px 24px rgba(0,0,0,0.3)" }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid var(--signal-audience)",
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div className="flex items-center gap-2.5">
          <div
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              background: "var(--signal-audience)",
              boxShadow: "0 0 8px rgba(77,171,247,0.4)",
            }}
          />
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "13px",
              fontWeight: 700,
              color: "var(--text-primary)",
              letterSpacing: "-0.01em",
            }}
          >
            Prospect Picker
          </span>
        </div>
        {/* Selected count badge */}
        <span
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            color: selectedCount > 0 ? "var(--accent)" : "var(--text-muted)",
            background: selectedCount > 0 ? "var(--accent-glow)" : "transparent",
            border: `1px solid ${selectedCount > 0 ? "rgba(0,212,170,0.25)" : "transparent"}`,
            borderRadius: "4px",
            padding: "2px 7px",
            transition: "all 0.2s",
          }}
        >
          {selectedCount} of {totalCount} selected
        </span>
      </div>

      {/* Toolbar */}
      <div
        style={{
          padding: "10px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        {/* Title filter */}
        <input
          type="text"
          placeholder="Filter by title…"
          value={titleFilter}
          onChange={(e) => setTitleFilter(e.target.value)}
          style={{
            flex: "1 1 140px",
            minWidth: "120px",
            padding: "5px 10px",
            borderRadius: "var(--radius-sm)",
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-default)",
            color: "var(--text-primary)",
            fontSize: "12px",
            fontFamily: "var(--font-body)",
            outline: "none",
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
          onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border-default)")}
        />

        {/* Sort dropdown */}
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          style={{
            padding: "5px 8px",
            borderRadius: "var(--radius-sm)",
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-default)",
            color: "var(--text-secondary)",
            fontSize: "11.5px",
            fontFamily: "var(--font-mono)",
            cursor: "pointer",
            outline: "none",
          }}
        >
          <option value="fit_score">Sort: Fit Score</option>
          <option value="urgency_score">Sort: Urgency</option>
        </select>

        {/* Bulk actions */}
        <button type="button" className="btn-ghost" style={{ fontSize: "11.5px", padding: "4px 10px" }} onClick={selectTop10}>
          Select Top 10
        </button>
        <button type="button" className="btn-ghost" style={{ fontSize: "11.5px", padding: "4px 10px" }} onClick={selectAll}>
          Select All
        </button>
        <button type="button" className="btn-ghost" style={{ fontSize: "11.5px", padding: "4px 10px" }} onClick={clearAll}>
          Clear
        </button>
      </div>

      {/* Prospect list */}
      <div
        style={{
          maxHeight: "340px",
          overflowY: "auto",
          overflowX: "hidden",
        }}
      >
        {filtered.length === 0 ? (
          <div
            style={{
              padding: "28px 20px",
              textAlign: "center",
              color: "var(--text-muted)",
              fontSize: "12px",
              fontFamily: "var(--font-mono)",
            }}
          >
            No prospects match the filter.
          </div>
        ) : (
          filtered.map((p, idx) => {
            const isChecked = selected.has(p.id);
            const isLast = idx === filtered.length - 1;
            return (
              <div
                key={p.id}
                onClick={() => toggle(p.id)}
                style={{
                  display: "grid",
                  gridTemplateColumns: "20px 1fr 80px 80px auto auto",
                  alignItems: "center",
                  gap: "12px",
                  padding: "9px 20px",
                  borderBottom: isLast ? "none" : "1px solid var(--border-subtle)",
                  background: isChecked ? "rgba(0,212,170,0.04)" : "transparent",
                  cursor: "pointer",
                  transition: "background 0.15s",
                }}
                onMouseEnter={(e) => {
                  if (!isChecked)
                    (e.currentTarget as HTMLElement).style.background = "var(--bg-surface-2)";
                }}
                onMouseLeave={(e) => {
                  if (!isChecked)
                    (e.currentTarget as HTMLElement).style.background = "transparent";
                }}
              >
                {/* Checkbox */}
                <div
                  style={{
                    width: "14px",
                    height: "14px",
                    borderRadius: "3px",
                    border: `1.5px solid ${isChecked ? "var(--accent)" : "var(--border-default)"}`,
                    background: isChecked ? "var(--accent)" : "transparent",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                    transition: "all 0.15s",
                  }}
                >
                  {isChecked && (
                    <svg width="8" height="6" viewBox="0 0 8 6" fill="none">
                      <path d="M1 3L3 5L7 1" stroke="#06070a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>

                {/* Name / title / company */}
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: "12.5px",
                      fontWeight: 600,
                      color: "var(--text-primary)",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {p.name}
                  </div>
                  <div
                    style={{
                      fontSize: "11px",
                      color: "var(--text-muted)",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {p.title} · {p.company}
                  </div>
                </div>

                {/* Fit score bar */}
                <ScoreBar value={p.fit_score} color="var(--accent)" />

                {/* Urgency score bar */}
                <ScoreBar value={p.urgency_score} color="var(--warning)" />

                {/* Angle pill */}
                <Pill label={p.angle_recommendation} colorKey="email" />

                {/* Channel pill */}
                <Pill label={p.channel_recommendation} colorKey={p.channel_recommendation} />
              </div>
            );
          })
        )}
      </div>

      {/* Column headers (sticky-ish, rendered above list as a legend) */}
      {/** kept simple — rendered as a footer action bar */}

      {/* Footer action bar */}
      <div
        style={{
          padding: "12px 20px",
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "10px",
          background: "var(--bg-surface-1)",
        }}
      >
        <div
          style={{
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
            color: selectedCount > 0 ? "var(--text-secondary)" : "var(--text-muted)",
          }}
        >
          {selectedCount > 0
            ? `${selectedCount} prospect${selectedCount !== 1 ? "s" : ""} queued for deployment`
            : "Select prospects to continue"}
        </div>
        <button
          type="button"
          disabled={selectedCount === 0 || isPendingAction}
          onClick={handleDeploy}
          style={{
            padding: "8px 18px",
            borderRadius: "var(--radius-sm)",
            background: selectedCount > 0 && !isPendingAction ? "var(--accent)" : "var(--bg-elevated)",
            border: "none",
            color: selectedCount > 0 && !isPendingAction ? "#06070a" : "var(--text-muted)",
            fontSize: "11.5px",
            fontWeight: 700,
            fontFamily: "var(--font-body)",
            letterSpacing: "0.02em",
            cursor: selectedCount > 0 && !isPendingAction ? "pointer" : "default",
            boxShadow: selectedCount > 0 && !isPendingAction ? "0 0 16px var(--accent-glow-strong)" : "none",
            transition: "all 0.2s",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
          onMouseEnter={(e) => {
            if (selectedCount > 0 && !isPendingAction) e.currentTarget.style.opacity = "0.88";
          }}
          onMouseLeave={(e) => {
            if (selectedCount > 0 && !isPendingAction) e.currentTarget.style.opacity = "1";
          }}
        >
          {isPendingAction ? (
            <>
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
              Queuing…
            </>
          ) : (
            "Deploy to Selected →"
          )}
        </button>
      </div>
    </div>
  );
}
