import { useState, useEffect } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

interface VariantMetric {
  variant_id: string;
  sent: number;
  opens: number;
  clicks: number;
  replies: number;
  bounces: number;
  open_rate: number;
  click_rate: number;
  reply_rate: number;
  bounce_rate: number;
}

interface Comparison {
  variant_a: string;
  variant_b: string;
  metric: string;
  rate_a: number;
  rate_b: number;
  chi_squared: number;
  significant: boolean;
  effect_size: number;
}

interface Significance {
  comparisons: Comparison[];
  winner_id: string | null;
  is_significant: boolean;
  recommendation: string;
}

interface Winner {
  variant_id: string;
  reply_rate: number;
  open_rate: number;
  sent: number;
}

interface EngagementData {
  session_id: string;
  total_sent: number;
  total_failed: number;
  total_events: number;
  variant_metrics: VariantMetric[];
  winner: Winner | null;
  significance: Significance | null;
  deployment_summary: {
    channels: Record<string, { sent: number; failed: number }>;
  };
}

// ---------------------------------------------------------------------------
// Metric pill
// ---------------------------------------------------------------------------

function MetricPill({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "12px 20px",
        background: "var(--bg-surface-2)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        minWidth: "100px",
      }}
    >
      <span
        style={{
          fontSize: "22px",
          fontFamily: "var(--font-mono)",
          fontWeight: 800,
          color,
          lineHeight: 1.1,
        }}
      >
        {value}
      </span>
      <span
        style={{
          fontSize: "10px",
          fontFamily: "var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--text-muted)",
          marginTop: "4px",
        }}
      >
        {label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rate bar
// ---------------------------------------------------------------------------

function RateBar({ label, rate, color }: { label: string; rate: number; color: string }) {
  const pct = Math.min(100, Math.round(rate * 100));
  return (
    <div style={{ marginBottom: "6px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "10px",
          fontFamily: "var(--font-mono)",
          color: "var(--text-muted)",
          marginBottom: "3px",
        }}
      >
        <span>{label}</span>
        <span style={{ color, fontWeight: 700 }}>{pct}%</span>
      </div>
      <div
        style={{
          height: "4px",
          borderRadius: "2px",
          background: "var(--bg-surface-3)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: "2px",
            background: color,
            transition: "width 0.6s ease",
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function EngagementDashboard({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<EngagementData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/campaign/${sessionId}/engagement`);
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const json: EngagementData = await res.json();
        if (!cancelled) setData(json);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (loading) {
    return (
      <div
        style={{
          padding: "40px",
          textAlign: "center",
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: "12px",
        }}
      >
        Loading engagement data…
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          padding: "20px",
          background: "rgba(255,77,106,0.07)",
          border: "1px solid rgba(255,77,106,0.2)",
          borderRadius: "var(--radius-md)",
          color: "var(--danger)",
          fontSize: "12px",
          fontFamily: "var(--font-mono)",
        }}
      >
        Error: {error}
      </div>
    );
  }

  if (!data) return null;

  const { variant_metrics, winner, significance, deployment_summary } = data;

  return (
    <div
      className="animate-fade-in-up"
      style={{
        background: "var(--bg-surface-1)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
        boxShadow: "0 0 40px rgba(0,212,170,0.04), 0 4px 24px rgba(0,0,0,0.3)",
      }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid var(--accent)",
          padding: "16px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "14px",
            fontWeight: 700,
            color: "var(--text-primary)",
          }}
        >
          Engagement Dashboard
        </span>
        <span
          style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          Session {sessionId.slice(0, 8)}
        </span>
      </div>

      {/* Summary pills */}
      <div
        style={{
          padding: "16px 20px",
          display: "flex",
          gap: "10px",
          flexWrap: "wrap",
        }}
      >
        <MetricPill label="Sent" value={data.total_sent} color="var(--text-primary)" />
        <MetricPill label="Failed" value={data.total_failed} color="var(--danger)" />
        <MetricPill label="Events" value={data.total_events} color="var(--accent)" />
        {Object.entries(deployment_summary.channels).map(([ch, stats]) => (
          <MetricPill
            key={ch}
            label={ch}
            value={`${stats.sent}/${stats.sent + stats.failed}`}
            color="var(--signal-channel)"
          />
        ))}
      </div>

      {/* Per-variant breakdown */}
      {variant_metrics.length > 0 && (
        <div style={{ padding: "0 20px 16px" }}>
          <div
            style={{
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: "var(--text-muted)",
              marginBottom: "10px",
            }}
          >
            Per-Variant Metrics
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {variant_metrics.map((v, i) => {
              const isWinner = winner?.variant_id === v.variant_id;
              const label = i === 0 ? "A" : i === 1 ? "B" : i === 2 ? "C" : `${i + 1}`;
              return (
                <div
                  key={v.variant_id}
                  style={{
                    background: isWinner
                      ? "linear-gradient(135deg, rgba(0,212,170,0.06) 0%, var(--bg-surface-2) 60%)"
                      : "var(--bg-surface-2)",
                    border: `1px solid ${isWinner ? "rgba(0,212,170,0.25)" : "var(--border-subtle)"}`,
                    borderRadius: "var(--radius-sm)",
                    padding: "12px 14px",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: "8px",
                    }}
                  >
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: "12px",
                        fontWeight: 700,
                        color: isWinner ? "var(--accent)" : "var(--text-primary)",
                      }}
                    >
                      Variant {label}{" "}
                      <span style={{ fontWeight: 400, color: "var(--text-muted)", fontSize: "10px" }}>
                        {v.variant_id.slice(0, 12)}
                      </span>
                    </span>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      {isWinner && (
                        <span
                          style={{
                            fontSize: "9px",
                            fontFamily: "var(--font-mono)",
                            fontWeight: 700,
                            color: "var(--accent)",
                            background: "var(--accent-glow)",
                            border: "1px solid rgba(0,212,170,0.2)",
                            borderRadius: "3px",
                            padding: "1px 6px",
                            textTransform: "uppercase",
                          }}
                        >
                          Winner
                        </span>
                      )}
                      <span
                        style={{
                          fontSize: "10px",
                          fontFamily: "var(--font-mono)",
                          color: "var(--text-muted)",
                        }}
                      >
                        n={v.sent}
                      </span>
                    </div>
                  </div>
                  <RateBar label="Open Rate" rate={v.open_rate} color="var(--signal-audience)" />
                  <RateBar label="Click Rate" rate={v.click_rate} color="var(--signal-channel)" />
                  <RateBar label="Reply Rate" rate={v.reply_rate} color="var(--accent)" />
                  <RateBar label="Bounce Rate" rate={v.bounce_rate} color="var(--danger)" />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Significance section */}
      {significance && significance.comparisons.length > 0 && (
        <div
          style={{
            margin: "0 20px 16px",
            padding: "14px",
            background: significance.is_significant
              ? "rgba(0,212,170,0.05)"
              : "var(--bg-surface-3)",
            border: `1px solid ${significance.is_significant ? "rgba(0,212,170,0.2)" : "var(--border-subtle)"}`,
            borderRadius: "var(--radius-sm)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              marginBottom: "10px",
            }}
          >
            <span
              style={{
                fontSize: "10px",
                fontFamily: "var(--font-mono)",
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: significance.is_significant ? "var(--accent)" : "var(--text-muted)",
              }}
            >
              A/B Significance (chi-squared)
            </span>
            <span
              style={{
                fontSize: "9px",
                fontFamily: "var(--font-mono)",
                padding: "1px 6px",
                borderRadius: "3px",
                background: significance.is_significant
                  ? "var(--accent-glow)"
                  : "var(--bg-elevated)",
                color: significance.is_significant ? "var(--accent)" : "var(--text-muted)",
                border: `1px solid ${significance.is_significant ? "rgba(0,212,170,0.2)" : "var(--border-subtle)"}`,
              }}
            >
              {significance.is_significant ? "SIGNIFICANT" : "NOT YET"}
            </span>
          </div>
          {significance.comparisons.map((comp, idx) => (
            <div
              key={idx}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "4px 0",
                fontSize: "11px",
                fontFamily: "var(--font-mono)",
                color: "var(--text-secondary)",
                borderBottom:
                  idx < significance.comparisons.length - 1
                    ? "1px solid var(--border-subtle)"
                    : "none",
              }}
            >
              <span>
                {comp.variant_a.slice(0, 8)} vs {comp.variant_b.slice(0, 8)}
              </span>
              <span style={{ display: "flex", gap: "12px" }}>
                <span>chi²={comp.chi_squared.toFixed(3)}</span>
                <span>Δ={Math.round(comp.effect_size * 100)}%</span>
                <span
                  style={{
                    color: comp.significant ? "var(--accent)" : "var(--text-muted)",
                    fontWeight: comp.significant ? 700 : 400,
                  }}
                >
                  {comp.significant ? "✓ sig" : "—"}
                </span>
              </span>
            </div>
          ))}
          {significance.recommendation && (
            <div
              style={{
                marginTop: "8px",
                fontSize: "11px",
                fontFamily: "var(--font-body)",
                color: significance.is_significant ? "var(--accent-dim)" : "var(--text-muted)",
                lineHeight: "1.5",
              }}
            >
              {significance.recommendation}
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {variant_metrics.length === 0 && (
        <div
          style={{
            padding: "32px 20px",
            textAlign: "center",
            color: "var(--text-muted)",
            fontSize: "13px",
            fontFamily: "var(--font-body)",
          }}
        >
          No deployment records found for this session.
        </div>
      )}
    </div>
  );
}
