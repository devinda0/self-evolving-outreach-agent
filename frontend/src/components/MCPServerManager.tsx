import { useState, useEffect, useCallback } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MCPTool {
  name: string;
  description: string;
  parameters: { name: string; type: string; description: string; required: boolean }[];
}

interface MCPServer {
  server_id: string;
  name: string;
  description: string;
  transport: "stdio" | "sse";
  command: string;
  args: string[];
  env_keys: string[];
  url: string | null;
  enabled: boolean;
  status: "stopped" | "starting" | "running" | "error";
  tools: MCPTool[];
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

interface MCPTemplate {
  template_id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  command: string;
  args: string[];
  env_keys: string[];
  env_descriptions: Record<string, string>;
  env_placeholders: Record<string, string>;
  transport: "stdio" | "sse";
  url_template: string | null;
  setup_hint: string;
}

type Step = "list" | "pick-template" | "configure" | "testing";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MCPServerManager({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<Step>("list");
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [templates, setTemplates] = useState<Record<string, MCPTemplate[]>>({});
  const [selectedTemplate, setSelectedTemplate] = useState<MCPTemplate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Configure step state
  const [configName, setConfigName] = useState("");
  const [configCommand, setConfigCommand] = useState("");
  const [configArgs, setConfigArgs] = useState("");
  const [configEnv, setConfigEnv] = useState<Record<string, string>>({});
  const [configUrl, setConfigUrl] = useState("");
  const [configTransport, setConfigTransport] = useState<"stdio" | "sse">("stdio");

  // Testing
  const [testResult, setTestResult] = useState<{ success: boolean; tools_discovered?: number; tools?: { name: string; description: string }[]; error?: string } | null>(null);

  const fetchServers = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/mcp/servers`);
      if (res.ok) setServers(await res.json());
    } catch {
      /* ignore */
    }
  }, []);

  const fetchTemplates = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/mcp/templates`);
      if (res.ok) {
        const data = await res.json();
        setTemplates(data.categories ?? {});
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    fetchServers();
    fetchTemplates();
  }, [fetchServers, fetchTemplates]);

  // -- Server list actions --

  async function toggleServer(s: MCPServer) {
    const endpoint = s.status === "running" ? "stop" : "start";
    await fetch(`${API_BASE}/mcp/servers/${s.server_id}/${endpoint}`, { method: "POST" });
    await fetchServers();
  }

  async function removeServer(serverId: string) {
    await fetch(`${API_BASE}/mcp/servers/${serverId}`, { method: "DELETE" });
    setServers((prev) => prev.filter((s) => s.server_id !== serverId));
  }

  // -- Template selection --

  function selectTemplate(t: MCPTemplate) {
    setSelectedTemplate(t);
    setConfigName(t.name);
    setConfigCommand(t.command);
    setConfigArgs(t.args.join(" "));
    setConfigTransport(t.transport);
    setConfigUrl(t.url_template ?? "");
    const envInit: Record<string, string> = {};
    for (const k of t.env_keys) envInit[k] = "";
    setConfigEnv(envInit);
    setStep("configure");
  }

  function startCustomConfig() {
    setSelectedTemplate(null);
    setConfigName("");
    setConfigCommand("");
    setConfigArgs("");
    setConfigTransport("stdio");
    setConfigUrl("");
    setConfigEnv({});
    setStep("configure");
  }

  // -- Create & test --

  async function handleCreate() {
    setLoading(true);
    setError(null);
    setTestResult(null);
    setStep("testing");

    try {
      const body: Record<string, unknown> = {
        name: configName,
        description: selectedTemplate?.description ?? "",
        transport: configTransport,
        command: configCommand,
        args: configArgs.split(/\s+/).filter(Boolean),
        env: configEnv,
      };
      if (configTransport === "sse" && configUrl) {
        body.url = configUrl;
      }

      const res = await fetch(`${API_BASE}/mcp/servers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to create server" }));
        throw new Error(err.detail ?? `Server returned ${res.status}`);
      }

      const created: MCPServer = await res.json();

      // Test connection
      const testRes = await fetch(`${API_BASE}/mcp/servers/${created.server_id}/test`, { method: "POST" });
      if (testRes.ok) {
        const tr = await testRes.json();
        setTestResult(tr);
      }

      await fetchServers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setTestResult({ success: false, error: err instanceof Error ? err.message : "Unknown error" });
    } finally {
      setLoading(false);
    }
  }

  // -- Status helpers --

  function statusDot(status: MCPServer["status"]) {
    const color = status === "running" ? "var(--success)" : status === "starting" ? "var(--warning)" : status === "error" ? "var(--danger)" : "var(--text-muted)";
    return (
      <span
        className="inline-block h-2 w-2 rounded-full"
        style={{ background: color, boxShadow: status === "running" ? `0 0 6px ${color}` : "none" }}
      />
    );
  }

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <div
      className="animate-fade-in"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 40,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.6)",
        backdropFilter: "blur(4px)",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="animate-fade-in-up"
        style={{
          width: "100%",
          maxWidth: "640px",
          maxHeight: "85vh",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          background: "var(--bg-surface-1)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-xl)",
          boxShadow: "0 0 80px rgba(0,212,170,0.06), 0 4px 60px rgba(0,0,0,0.5)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between shrink-0"
          style={{ padding: "16px 20px", borderBottom: "1px solid var(--border-subtle)" }}
        >
          <div className="flex items-center gap-2.5">
            {step !== "list" && (
              <button
                onClick={() => { setStep(step === "testing" ? "configure" : step === "configure" ? "pick-template" : "list"); setError(null); setTestResult(null); }}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", padding: 0, display: "flex" }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
            )}
            <div
              className="flex h-7 w-7 items-center justify-center rounded-md"
              style={{ background: "var(--accent-glow)", border: "1px solid rgba(0,212,170,0.15)" }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
            </div>
            <div>
              <h2 style={{ fontFamily: "var(--font-display)", fontSize: "15px", fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
                {step === "list" ? "MCP Servers" : step === "pick-template" ? "Add Server" : step === "configure" ? "Configure" : "Testing Connection"}
              </h2>
              <p style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "1px" }}>
                {step === "list" ? "Manage tool integrations" : step === "pick-template" ? "Choose a server template" : step === "configure" ? (selectedTemplate?.name ?? "Custom server") : "Verifying server connection…"}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", padding: "4px" }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>

          {/* ====== STEP: Server List ====== */}
          {step === "list" && (
            <div className="space-y-3">
              {servers.length === 0 ? (
                <div className="flex flex-col items-center gap-3 py-8">
                  <div
                    style={{
                      width: "48px",
                      height: "48px",
                      borderRadius: "var(--radius-lg)",
                      background: "var(--bg-surface-2)",
                      border: "1px solid var(--border-subtle)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
                      <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
                      <line x1="6" y1="6" x2="6.01" y2="6" />
                      <line x1="6" y1="18" x2="6.01" y2="18" />
                    </svg>
                  </div>
                  <p style={{ fontSize: "13px", color: "var(--text-muted)", textAlign: "center" }}>
                    No MCP servers configured yet.
                    <br />
                    <span style={{ fontSize: "12px" }}>Add one to extend your agent capabilities.</span>
                  </p>
                  <button onClick={() => setStep("pick-template")} className="btn-accent" style={{ padding: "10px 20px", fontSize: "12px", borderRadius: "var(--radius-md)" }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="12" y1="5" x2="12" y2="19" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                    Add Your First Server
                  </button>
                </div>
              ) : (
                <>
                  {servers.map((s, i) => (
                    <div
                      key={s.server_id}
                      className="surface-card animate-fade-in-up"
                      style={{ padding: "14px 16px", animationDelay: `${i * 40}ms` }}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-2.5">
                          {statusDot(s.status)}
                          <div>
                            <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-primary)" }}>
                              {s.name}
                            </div>
                            <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                              {s.description || s.command}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => toggleServer(s)}
                            className="btn-ghost"
                            style={{ padding: "4px 10px", fontSize: "11px" }}
                          >
                            {s.status === "running" ? "Stop" : "Start"}
                          </button>
                          <button
                            onClick={() => removeServer(s.server_id)}
                            style={{
                              background: "none",
                              border: "none",
                              cursor: "pointer",
                              color: "var(--text-muted)",
                              padding: "4px",
                              transition: "color 0.2s",
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--danger)")}
                            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <polyline points="3 6 5 6 21 6" />
                              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            </svg>
                          </button>
                        </div>
                      </div>

                      {/* Error */}
                      {s.error_message && (
                        <div style={{ marginTop: "8px", padding: "8px 10px", background: "rgba(255,77,106,0.08)", borderRadius: "var(--radius-sm)", border: "1px solid rgba(255,77,106,0.15)" }}>
                          <p style={{ fontSize: "11px", color: "var(--danger)", margin: 0 }}>{s.error_message}</p>
                        </div>
                      )}

                      {/* Tools */}
                      {s.status === "running" && s.tools.length > 0 && (
                        <div style={{ marginTop: "10px", display: "flex", flexWrap: "wrap", gap: "4px" }}>
                          {s.tools.map((t) => (
                            <span
                              key={t.name}
                              style={{
                                fontSize: "10px",
                                fontFamily: "var(--font-mono)",
                                color: "var(--accent)",
                                background: "var(--accent-glow)",
                                padding: "2px 8px",
                                borderRadius: "3px",
                                border: "1px solid rgba(0,212,170,0.12)",
                              }}
                              title={t.description}
                            >
                              {t.name}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  <button
                    onClick={() => setStep("pick-template")}
                    className="btn-ghost w-full justify-center"
                    style={{ padding: "10px", fontSize: "12px", marginTop: "4px" }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="12" y1="5" x2="12" y2="19" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                    Add Another Server
                  </button>
                </>
              )}
            </div>
          )}

          {/* ====== STEP: Pick Template ====== */}
          {step === "pick-template" && (
            <div className="space-y-4">
              {Object.entries(templates).map(([category, tmps]) => (
                <div key={category}>
                  <h3 style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-muted)", marginBottom: "8px" }}>
                    {category}
                  </h3>
                  <div className="space-y-2">
                    {tmps.map((t) => (
                      <button
                        key={t.template_id}
                        onClick={() => selectTemplate(t)}
                        className="w-full text-left"
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "12px",
                          padding: "12px 14px",
                          background: "var(--bg-surface-2)",
                          border: "1px solid var(--border-subtle)",
                          borderRadius: "var(--radius-md)",
                          cursor: "pointer",
                          transition: "border-color 0.2s, background 0.2s",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = "var(--accent)";
                          e.currentTarget.style.background = "var(--bg-surface-3)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = "var(--border-subtle)";
                          e.currentTarget.style.background = "var(--bg-surface-2)";
                        }}
                      >
                        <span style={{ fontSize: "20px" }}>{t.icon}</span>
                        <div className="flex-1 min-w-0">
                          <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-primary)" }}>{t.name}</div>
                          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>{t.description}</div>
                        </div>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.5, flexShrink: 0 }}>
                          <polyline points="9 18 15 12 9 6" />
                        </svg>
                      </button>
                    ))}
                  </div>
                </div>
              ))}

              {/* Custom server option */}
              <button
                onClick={startCustomConfig}
                className="w-full text-left"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                  padding: "12px 14px",
                  background: "var(--bg-surface-2)",
                  border: "1px dashed var(--border-default)",
                  borderRadius: "var(--radius-md)",
                  cursor: "pointer",
                  transition: "border-color 0.2s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border-default)")}
              >
                <span style={{ fontSize: "20px" }}>⚙️</span>
                <div>
                  <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-primary)" }}>Custom Server</div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Configure any MCP server manually</div>
                </div>
              </button>
            </div>
          )}

          {/* ====== STEP: Configure ====== */}
          {step === "configure" && (
            <div className="space-y-4">
              {selectedTemplate?.setup_hint && (
                <div style={{ padding: "10px 14px", background: "var(--accent-glow)", borderRadius: "var(--radius-sm)", border: "1px solid rgba(0,212,170,0.12)" }}>
                  <p style={{ fontSize: "12px", color: "var(--accent)", margin: 0 }}>
                    💡 {selectedTemplate.setup_hint}
                  </p>
                </div>
              )}

              <label className="block">
                <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
                  Server Name
                </span>
                <input
                  value={configName}
                  onChange={(e) => setConfigName(e.target.value)}
                  placeholder="My Server"
                  className="mt-1.5 block w-full outline-none placeholder:opacity-30"
                  style={{
                    background: "var(--bg-surface-2)",
                    border: "1px solid var(--border-default)",
                    borderRadius: "var(--radius-md)",
                    padding: "9px 12px",
                    fontSize: "13px",
                    color: "var(--text-primary)",
                  }}
                />
              </label>

              {/* Transport toggle */}
              {!selectedTemplate && (
                <div>
                  <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", display: "block", marginBottom: "6px" }}>
                    Transport
                  </span>
                  <div className="flex gap-2">
                    {(["stdio", "sse"] as const).map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setConfigTransport(t)}
                        className={configTransport === t ? "btn-accent" : "btn-ghost"}
                        style={{ padding: "6px 14px", fontSize: "11px" }}
                      >
                        {t.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {configTransport === "stdio" ? (
                <>
                  <label className="block">
                    <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
                      Command
                    </span>
                    <input
                      value={configCommand}
                      onChange={(e) => setConfigCommand(e.target.value)}
                      placeholder="npx"
                      className="mt-1.5 block w-full outline-none placeholder:opacity-30"
                      style={{
                        background: "var(--bg-surface-2)",
                        border: "1px solid var(--border-default)",
                        borderRadius: "var(--radius-md)",
                        padding: "9px 12px",
                        fontSize: "13px",
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-primary)",
                      }}
                    />
                  </label>

                  <label className="block">
                    <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
                      Arguments
                    </span>
                    <input
                      value={configArgs}
                      onChange={(e) => setConfigArgs(e.target.value)}
                      placeholder="-y @modelcontextprotocol/server-name"
                      className="mt-1.5 block w-full outline-none placeholder:opacity-30"
                      style={{
                        background: "var(--bg-surface-2)",
                        border: "1px solid var(--border-default)",
                        borderRadius: "var(--radius-md)",
                        padding: "9px 12px",
                        fontSize: "13px",
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-primary)",
                      }}
                    />
                  </label>
                </>
              ) : (
                <label className="block">
                  <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
                    SSE Endpoint URL
                  </span>
                  <input
                    value={configUrl}
                    onChange={(e) => setConfigUrl(e.target.value)}
                    placeholder="http://localhost:3000/sse"
                    className="mt-1.5 block w-full outline-none placeholder:opacity-30"
                    style={{
                      background: "var(--bg-surface-2)",
                      border: "1px solid var(--border-default)",
                      borderRadius: "var(--radius-md)",
                      padding: "9px 12px",
                      fontSize: "13px",
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-primary)",
                    }}
                  />
                </label>
              )}

              {/* Environment variables */}
              {Object.keys(configEnv).length > 0 && (
                <div className="space-y-3">
                  <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", display: "block" }}>
                    Environment Variables
                  </span>
                  {Object.entries(configEnv).map(([key]) => (
                    <label key={key} className="block">
                      <div className="flex items-center gap-2">
                        <span style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--accent)" }}>{key}</span>
                        {selectedTemplate?.env_descriptions[key] && (
                          <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                            — {selectedTemplate.env_descriptions[key]}
                          </span>
                        )}
                      </div>
                      <input
                        type="password"
                        value={configEnv[key] ?? ""}
                        onChange={(e) => setConfigEnv((prev) => ({ ...prev, [key]: e.target.value }))}
                        placeholder={selectedTemplate?.env_placeholders[key] ?? "Enter value…"}
                        className="mt-1 block w-full outline-none placeholder:opacity-30"
                        style={{
                          background: "var(--bg-surface-2)",
                          border: "1px solid var(--border-default)",
                          borderRadius: "var(--radius-md)",
                          padding: "9px 12px",
                          fontSize: "13px",
                          fontFamily: "var(--font-mono)",
                          color: "var(--text-primary)",
                        }}
                      />
                    </label>
                  ))}
                </div>
              )}

              {/* Add env var (custom only) */}
              {!selectedTemplate && (
                <button
                  type="button"
                  onClick={() => {
                    const key = prompt("Environment variable name:");
                    if (key && key.trim()) {
                      setConfigEnv((prev) => ({ ...prev, [key.trim()]: "" }));
                    }
                  }}
                  className="btn-ghost"
                  style={{ fontSize: "11px", padding: "6px 12px" }}
                >
                  + Add Environment Variable
                </button>
              )}

              {error && (
                <div style={{ padding: "8px 12px", background: "rgba(255,77,106,0.08)", borderRadius: "var(--radius-sm)", border: "1px solid rgba(255,77,106,0.15)" }}>
                  <p style={{ fontSize: "12px", color: "var(--danger)", margin: 0 }}>{error}</p>
                </div>
              )}
            </div>
          )}

          {/* ====== STEP: Testing ====== */}
          {step === "testing" && (
            <div className="flex flex-col items-center gap-4 py-8">
              {loading ? (
                <>
                  <div className="thinking-orb-container" style={{ width: 48, height: 48, position: "relative" }}>
                    <span className="inline-block h-10 w-10 animate-spin rounded-full border-2 border-current border-t-transparent" style={{ color: "var(--accent)" }} />
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <p style={{ fontSize: "13px", color: "var(--text-primary)", fontWeight: 600 }}>Connecting to server…</p>
                    <p style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>Initializing and discovering tools</p>
                  </div>
                </>
              ) : testResult ? (
                testResult.success ? (
                  <>
                    <div
                      style={{
                        width: "48px",
                        height: "48px",
                        borderRadius: "50%",
                        background: "rgba(0,212,126,0.12)",
                        border: "2px solid var(--success)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--success)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </div>
                    <div style={{ textAlign: "center" }}>
                      <p style={{ fontSize: "14px", fontWeight: 700, color: "var(--text-primary)" }}>Server Connected!</p>
                      <p style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>
                        Discovered <span style={{ color: "var(--accent)", fontWeight: 600 }}>{testResult.tools_discovered}</span> tool{testResult.tools_discovered !== 1 ? "s" : ""}
                      </p>
                    </div>
                    {testResult.tools && testResult.tools.length > 0 && (
                      <div style={{ width: "100%", maxWidth: "400px" }} className="space-y-1.5">
                        {testResult.tools.map((t) => (
                          <div
                            key={t.name}
                            style={{
                              padding: "8px 12px",
                              background: "var(--bg-surface-2)",
                              borderRadius: "var(--radius-sm)",
                              border: "1px solid var(--border-subtle)",
                            }}
                          >
                            <div style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--accent)", fontWeight: 600 }}>{t.name}</div>
                            {t.description && (
                              <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>{t.description}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    <button
                      onClick={() => { setStep("list"); setTestResult(null); }}
                      className="btn-accent"
                      style={{ padding: "10px 24px", fontSize: "12px", borderRadius: "var(--radius-md)" }}
                    >
                      Done
                    </button>
                  </>
                ) : (
                  <>
                    <div
                      style={{
                        width: "48px",
                        height: "48px",
                        borderRadius: "50%",
                        background: "rgba(255,77,106,0.1)",
                        border: "2px solid var(--danger)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                      </svg>
                    </div>
                    <div style={{ textAlign: "center" }}>
                      <p style={{ fontSize: "14px", fontWeight: 700, color: "var(--text-primary)" }}>Connection Failed</p>
                      <p style={{ fontSize: "12px", color: "var(--danger)", marginTop: "4px" }}>{testResult.error}</p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => { setStep("configure"); setTestResult(null); setError(null); }}
                        className="btn-ghost"
                        style={{ padding: "8px 16px", fontSize: "12px" }}
                      >
                        Edit Config
                      </button>
                      <button
                        onClick={handleCreate}
                        className="btn-accent"
                        style={{ padding: "8px 16px", fontSize: "12px" }}
                      >
                        Retry
                      </button>
                    </div>
                  </>
                )
              ) : null}
            </div>
          )}
        </div>

        {/* Footer — only on configure step */}
        {step === "configure" && (
          <div
            className="shrink-0 flex justify-end gap-2"
            style={{ padding: "12px 20px", borderTop: "1px solid var(--border-subtle)" }}
          >
            <button
              onClick={() => { setStep("pick-template"); setError(null); }}
              className="btn-ghost"
              style={{ padding: "8px 16px", fontSize: "12px" }}
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={!configName.trim() || (configTransport === "stdio" && !configCommand.trim())}
              className="btn-accent disabled:opacity-40"
              style={{ padding: "8px 20px", fontSize: "12px", borderRadius: "var(--radius-md)" }}
            >
              Connect & Test
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
