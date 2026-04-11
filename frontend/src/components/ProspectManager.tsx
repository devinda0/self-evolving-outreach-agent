import { useState, useMemo, useRef, useCallback } from "react";
import type { UIFrame, UIAction } from "../store/campaignStore";
import { useCampaignStore } from "../store/campaignStore";

interface Prospect {
  id: string;
  name: string;
  email?: string | null;
  title: string;
  company: string;
  fit_score: number;
  urgency_score: number;
  angle_recommendation: string;
  channel_recommendation: string;
  source?: string;
}

type SortKey = "fit_score" | "urgency_score" | "name";

interface Props {
  frame: UIFrame;
  onAction: (instanceId: string, actionId: string, payload: Record<string, unknown>) => void;
}

// ---------- sub-components ----------

function ScoreBar({ value, color }: { value: number; color: string }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "6px", minWidth: "70px" }}>
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

const SOURCE_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  manual:    { label: "MANUAL",    color: "var(--accent)",           bg: "rgba(0,212,170,0.1)" },
  csv:       { label: "CSV",       color: "var(--signal-channel)",   bg: "rgba(81,207,102,0.1)" },
  discovery: { label: "DISCOVERED",color: "var(--signal-audience)",  bg: "rgba(77,171,247,0.1)" },
  seed:      { label: "SEED",      color: "var(--text-muted)",       bg: "var(--bg-elevated)" },
};

const CHANNEL_STYLES: Record<string, { color: string; bg: string }> = {
  email:    { color: "var(--signal-audience)", bg: "rgba(77,171,247,0.1)" },
  linkedin: { color: "var(--signal-market)",   bg: "rgba(255,212,59,0.1)" },
  twitter:  { color: "#74c0fc",                bg: "rgba(116,192,252,0.1)" },
  sms:      { color: "var(--signal-channel)",  bg: "rgba(81,207,102,0.1)" },
};

function Pill({ label, colorKey }: { label: string; colorKey?: string }) {
  const key = (colorKey ?? label).toLowerCase();
  const s = CHANNEL_STYLES[key] ?? { color: "var(--text-muted)", bg: "var(--bg-elevated)" };
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

function SourceBadge({ source }: { source: string }) {
  const s = SOURCE_STYLES[source] ?? SOURCE_STYLES.seed!;
  return (
    <span
      style={{
        fontSize: "8.5px",
        fontWeight: 700,
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.06em",
        color: s.color,
        background: s.bg,
        border: `1px solid ${s.color}22`,
        borderRadius: "3px",
        padding: "1px 5px",
      }}
    >
      {s.label}
    </span>
  );
}

// ---------- Add Prospect Form ----------

function AddProspectForm({ onAdd, onCancel }: { onAdd: (data: Record<string, string>) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  function validate() {
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = "Name is required";
    if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) errs.email = "Invalid email";
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    onAdd({ name: name.trim(), email: email.trim(), title: title.trim(), company: company.trim() });
    setName(""); setEmail(""); setTitle(""); setCompany("");
    setErrors({});
  }

  const inputStyle = (hasError: boolean) => ({
    width: "100%",
    padding: "7px 10px",
    borderRadius: "var(--radius-sm)",
    background: "var(--bg-surface-2)",
    border: `1px solid ${hasError ? "var(--danger)" : "var(--border-default)"}`,
    color: "var(--text-primary)",
    fontSize: "12px",
    fontFamily: "var(--font-body)",
    outline: "none",
  });

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        padding: "14px 20px",
        borderBottom: "1px solid var(--border-subtle)",
        background: "rgba(0,212,170,0.02)",
        animation: "fade-in-up 0.3s ease-out both",
      }}
    >
      <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--accent)", marginBottom: "10px", fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>
        + ADD PROSPECT
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "8px" }}>
        <div>
          <input placeholder="Name *" value={name} onChange={(e) => setName(e.target.value)} style={inputStyle(!!errors.name)} />
          {errors.name && <span style={{ fontSize: "10px", color: "var(--danger)", marginTop: "2px", display: "block" }}>{errors.name}</span>}
        </div>
        <div>
          <input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} style={inputStyle(!!errors.email)} />
          {errors.email && <span style={{ fontSize: "10px", color: "var(--danger)", marginTop: "2px", display: "block" }}>{errors.email}</span>}
        </div>
        <input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle(false)} />
        <input placeholder="Company" value={company} onChange={(e) => setCompany(e.target.value)} style={inputStyle(false)} />
      </div>
      <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
        <button
          type="button"
          onClick={onCancel}
          style={{
            padding: "5px 14px",
            borderRadius: "var(--radius-sm)",
            background: "transparent",
            border: "1px solid var(--border-default)",
            color: "var(--text-secondary)",
            fontSize: "11.5px",
            cursor: "pointer",
          }}
        >
          Cancel
        </button>
        <button
          type="submit"
          style={{
            padding: "5px 14px",
            borderRadius: "var(--radius-sm)",
            background: "var(--accent)",
            border: "none",
            color: "#06070a",
            fontSize: "11.5px",
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          Add
        </button>
      </div>
    </form>
  );
}

// ---------- CSV Upload ----------

function CsvUpload({
  sessionId,
  onUploadComplete,
  onCancel,
}: {
  sessionId: string | null;
  onUploadComplete: () => void;
  onCancel: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ imported: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

  function validateFile(f: File): string | null {
    if (!f.name.toLowerCase().endsWith(".csv")) return "Only CSV files are accepted";
    if (f.size > 5 * 1024 * 1024) return "File must be smaller than 5MB";
    if (f.size === 0) return "File is empty";
    return null;
  }

  async function handleUpload() {
    if (!file || !sessionId) return;
    const validationError = validateFile(file);
    if (validationError) { setError(validationError); return; }

    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const resp = await fetch(`${API_BASE}/campaign/${sessionId}/prospects/import`, {
        method: "POST",
        body: formData,
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(body.detail || "Upload failed");
      }
      const data = await resp.json();
      setResult({ imported: data.imported });
      setTimeout(onUploadComplete, 1500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div
      style={{
        padding: "14px 20px",
        borderBottom: "1px solid var(--border-subtle)",
        background: "rgba(81,207,102,0.02)",
        animation: "fade-in-up 0.3s ease-out both",
      }}
    >
      <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--signal-channel)", marginBottom: "10px", fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>
        ↑ UPLOAD CSV
      </div>

      {result ? (
        <div style={{ fontSize: "12px", color: "var(--success)", display: "flex", alignItems: "center", gap: "6px" }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.5"/><path d="M4 7L6 9L10 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
          Imported {result.imported} prospects
        </div>
      ) : (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError(null); }}
              style={{ display: "none" }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              style={{
                padding: "6px 14px",
                borderRadius: "var(--radius-sm)",
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-default)",
                color: "var(--text-secondary)",
                fontSize: "12px",
                cursor: "pointer",
              }}
            >
              Choose File
            </button>
            <span style={{ fontSize: "12px", color: file ? "var(--text-primary)" : "var(--text-muted)" }}>
              {file ? file.name : "No file selected"}
            </span>
          </div>

          <div style={{ fontSize: "10px", color: "var(--text-muted)", marginBottom: "10px", fontFamily: "var(--font-mono)" }}>
            CSV columns: name, email, title, company, linkedin_url (auto-detected)
          </div>

          {error && (
            <div style={{ fontSize: "11px", color: "var(--danger)", marginBottom: "8px" }}>
              {error}
            </div>
          )}

          <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
            <button
              type="button"
              onClick={onCancel}
              style={{
                padding: "5px 14px",
                borderRadius: "var(--radius-sm)",
                background: "transparent",
                border: "1px solid var(--border-default)",
                color: "var(--text-secondary)",
                fontSize: "11.5px",
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!file || uploading}
              onClick={handleUpload}
              style={{
                padding: "5px 14px",
                borderRadius: "var(--radius-sm)",
                background: file && !uploading ? "var(--signal-channel)" : "var(--bg-elevated)",
                border: "none",
                color: file && !uploading ? "#06070a" : "var(--text-muted)",
                fontSize: "11.5px",
                fontWeight: 700,
                cursor: file && !uploading ? "pointer" : "default",
                opacity: uploading ? 0.6 : 1,
              }}
            >
              {uploading ? "Uploading…" : "Upload"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ---------- main component ----------

export default function ProspectManager({ frame, onAction }: Props) {
  const prospects = (frame.props.prospects as Prospect[]) ?? [];
  const initialSelected = (frame.props.selected_ids as string[]) ?? [];
  const message = (frame.props.message as string) ?? "";
  const showCsvUpload = (frame.props.show_csv_upload as boolean) ?? false;

  const sessionId = useCampaignStore((s) => s.sessionId);
  const isPendingAction = useCampaignStore((s) => s.isPendingAction);

  const [selected, setSelected] = useState<Set<string>>(new Set(initialSelected));
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("fit_score");
  const [showAddForm, setShowAddForm] = useState(false);
  const [showCsv, setShowCsv] = useState(showCsvUpload);
  const [localProspects, setLocalProspects] = useState<Prospect[]>(prospects);

  const confirmAction = frame.actions.find(
    (a: UIAction) => a.action_type === "confirm_prospects" || a.id === "confirm-prospects"
  );

  // Derived: filtered + sorted
  const filtered = useMemo(() => {
    const lower = filter.toLowerCase().trim();
    return [...localProspects]
      .filter((p) => {
        if (!lower) return true;
        return (
          p.name.toLowerCase().includes(lower) ||
          p.title.toLowerCase().includes(lower) ||
          p.company.toLowerCase().includes(lower) ||
          (p.email || "").toLowerCase().includes(lower)
        );
      })
      .sort((a, b) => {
        if (sortKey === "name") return a.name.localeCompare(b.name);
        return b[sortKey] - a[sortKey];
      });
  }, [localProspects, filter, sortKey]);

  const sortedByFit = useMemo(
    () => [...localProspects].sort((a, b) => b.fit_score - a.fit_score),
    [localProspects]
  );

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll() { setSelected(new Set(filtered.map((p) => p.id))); }
  function selectTop10() { setSelected(new Set(sortedByFit.slice(0, 10).map((p) => p.id))); }
  function clearAll() { setSelected(new Set()); }

  function removeSelected() {
    const idsToRemove = new Set(selected);
    setLocalProspects((prev) => prev.filter((p) => !idsToRemove.has(p.id)));
    setSelected(new Set());
    // Notify backend
    onAction(frame.instance_id, "remove-selected", {
      prospect_ids: Array.from(idsToRemove),
    });
  }

  const handleAddProspect = useCallback((data: Record<string, string>) => {
    const tempId = `prospect-temp-${Date.now()}`;
    const newProspect: Prospect = {
      id: tempId,
      name: data.name ?? "",
      email: data.email || null,
      title: data.title || "",
      company: data.company || "",
      fit_score: 0.75,
      urgency_score: 0.60,
      angle_recommendation: "value-proposition",
      channel_recommendation: data.email ? "email" : "linkedin",
      source: "manual",
    };
    setLocalProspects((prev) => [...prev, newProspect]);
    setSelected((prev) => new Set([...prev, tempId]));
    setShowAddForm(false);

    // Notify backend via chat
    onAction(frame.instance_id, "add-prospect-manual", {
      name: data.name,
      email: data.email,
      title: data.title,
      company: data.company,
    });
  }, [frame.instance_id, onAction]);

  function handleConfirm() {
    const selected_ids = Array.from(selected);
    if (confirmAction) {
      onAction(frame.instance_id, confirmAction.id, {
        ...confirmAction.payload,
        selected_ids,
      });
    } else {
      onAction(frame.instance_id, "confirm-prospects", { selected_ids });
    }
  }

  const selectedCount = selected.size;
  const totalCount = localProspects.length;

  return (
    <div
      className="surface-card overflow-hidden"
      style={{ boxShadow: "0 0 40px rgba(0,212,170,0.04), 0 4px 24px rgba(0,0,0,0.3)" }}
    >
      {/* Header */}
      <div
        style={{
          borderTop: "2px solid var(--accent)",
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
              background: "var(--accent)",
              boxShadow: "0 0 8px rgba(0,212,170,0.4)",
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
            Prospect Manager
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
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
      </div>

      {/* Status message */}
      {message && (
        <div
          style={{
            padding: "10px 20px",
            borderBottom: "1px solid var(--border-subtle)",
            fontSize: "12px",
            color: "var(--text-secondary)",
            fontFamily: "var(--font-body)",
            background: "rgba(0,212,170,0.02)",
          }}
        >
          {message}
        </div>
      )}

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
        {/* Search filter */}
        <input
          type="text"
          placeholder="Search name, title, company, email…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{
            flex: "1 1 180px",
            minWidth: "140px",
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
          <option value="name">Sort: Name</option>
        </select>

        {/* Bulk actions */}
        <button type="button" className="btn-ghost" style={{ fontSize: "11.5px", padding: "4px 10px" }} onClick={selectTop10}>
          Top 10
        </button>
        <button type="button" className="btn-ghost" style={{ fontSize: "11.5px", padding: "4px 10px" }} onClick={selectAll}>
          All
        </button>
        <button type="button" className="btn-ghost" style={{ fontSize: "11.5px", padding: "4px 10px" }} onClick={clearAll}>
          Clear
        </button>
        {selectedCount > 0 && (
          <button
            type="button"
            className="btn-ghost"
            style={{ fontSize: "11.5px", padding: "4px 10px", color: "var(--danger)" }}
            onClick={removeSelected}
          >
            Remove ({selectedCount})
          </button>
        )}

        {/* Management actions */}
        <div style={{ borderLeft: "1px solid var(--border-subtle)", height: "20px", margin: "0 2px" }} />
        <button
          type="button"
          className="btn-ghost"
          style={{ fontSize: "11.5px", padding: "4px 10px", color: "var(--accent)" }}
          onClick={() => { setShowAddForm(!showAddForm); setShowCsv(false); }}
        >
          + Add
        </button>
        <button
          type="button"
          className="btn-ghost"
          style={{ fontSize: "11.5px", padding: "4px 10px", color: "var(--signal-channel)" }}
          onClick={() => { setShowCsv(!showCsv); setShowAddForm(false); }}
        >
          ↑ CSV
        </button>
      </div>

      {/* Add prospect form */}
      {showAddForm && (
        <AddProspectForm onAdd={handleAddProspect} onCancel={() => setShowAddForm(false)} />
      )}

      {/* CSV upload */}
      {showCsv && (
        <CsvUpload
          sessionId={sessionId}
          onUploadComplete={() => {
            setShowCsv(false);
            // Trigger a refresh by notifying the backend
            onAction(frame.instance_id, "csv-upload-complete", {});
          }}
          onCancel={() => setShowCsv(false)}
        />
      )}

      {/* Prospect list */}
      <div style={{ maxHeight: "380px", overflowY: "auto", overflowX: "hidden" }}>
        {filtered.length === 0 ? (
          <div
            style={{
              padding: "32px 20px",
              textAlign: "center",
              color: "var(--text-muted)",
              fontSize: "12px",
              fontFamily: "var(--font-mono)",
            }}
          >
            {totalCount === 0
              ? "No prospects yet. Add manually or upload a CSV."
              : "No prospects match the filter."}
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
                  gridTemplateColumns: "20px 1fr auto 70px 70px auto",
                  alignItems: "center",
                  gap: "10px",
                  padding: "9px 20px",
                  borderBottom: isLast ? "none" : "1px solid var(--border-subtle)",
                  background: isChecked ? "rgba(0,212,170,0.04)" : "transparent",
                  cursor: "pointer",
                  transition: "background 0.15s",
                }}
                onMouseEnter={(e) => {
                  if (!isChecked) (e.currentTarget as HTMLElement).style.background = "var(--bg-surface-2)";
                }}
                onMouseLeave={(e) => {
                  if (!isChecked) (e.currentTarget as HTMLElement).style.background = "transparent";
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

                {/* Name / title / company / email */}
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span
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
                    </span>
                    <SourceBadge source={p.source ?? "seed"} />
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
                    {p.title}{p.title && p.company ? " · " : ""}{p.company}
                    {p.email && (
                      <span style={{ marginLeft: "6px", color: "var(--text-muted)", fontSize: "10px" }}>
                        {p.email}
                      </span>
                    )}
                  </div>
                </div>

                {/* Channel pill */}
                <Pill label={p.channel_recommendation} colorKey={p.channel_recommendation} />

                {/* Fit score */}
                <ScoreBar value={p.fit_score} color="var(--accent)" />

                {/* Urgency score */}
                <ScoreBar value={p.urgency_score} color="var(--warning)" />

                {/* Angle pill */}
                <Pill label={p.angle_recommendation} colorKey="email" />
              </div>
            );
          })
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          borderTop: "1px solid var(--border-subtle)",
          padding: "12px 20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div
          style={{
            fontSize: "11px",
            color: selectedCount > 0 ? "var(--text-secondary)" : "var(--text-muted)",
            fontFamily: "var(--font-mono)",
          }}
        >
          {selectedCount > 0
            ? `${selectedCount} prospect${selectedCount !== 1 ? "s" : ""} queued for deployment`
            : "Select prospects to continue"}
        </div>
        <button
          type="button"
          disabled={selectedCount === 0 || isPendingAction}
          onClick={handleConfirm}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
            padding: "7px 18px",
            borderRadius: "var(--radius-sm)",
            background: selectedCount > 0 && !isPendingAction ? "var(--accent)" : "var(--bg-elevated)",
            border: "none",
            color: selectedCount > 0 && !isPendingAction ? "#06070a" : "var(--text-muted)",
            fontSize: "12px",
            fontWeight: 700,
            fontFamily: "var(--font-display)",
            letterSpacing: "-0.01em",
            cursor: selectedCount > 0 && !isPendingAction ? "pointer" : "default",
            transition: "all 0.2s",
          }}
        >
          {isPendingAction ? (
            <>
              <span style={{ animation: "spin-slow 1s linear infinite", display: "inline-block" }}>↻</span>
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
