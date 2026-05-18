"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { Activity, Bell, BookOpen, Download, FileText, Loader2, RefreshCw, ShieldCheck, Trash2, UserPlus } from "lucide-react";
import { apiClient, type AdminNotification, type HealthReport, type ServiceHealth } from "@/lib/api";
import { downloadAgentManualMarkdown, downloadAgentManualPdf } from "@/lib/agent-manual-export";
import { getUserInfo } from "@/lib/auth";

type AdminUser = {
  id: string;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  must_change_password: boolean;
  created_at: string;
};

type Tab = "users" | "manual" | "health" | "notifications";

// ── API Health Panel ──────────────────────────────────────────────────────────

const STATUS_COLOR: Record<ServiceHealth["status"], string> = {
  ok:      "#16a34a",
  error:   "var(--color-danger, #dc2626)",
  unknown: "var(--color-text-tertiary)",
};
const STATUS_LABEL: Record<ServiceHealth["status"], string> = { ok: "OK", error: "Error", unknown: "Unknown" };

function ServiceRow({ svc }: { svc: ServiceHealth }) {
  const color = STATUS_COLOR[svc.status];
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 0", borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
      <div style={{ marginTop: 3, width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
          <span style={{ fontSize: 13, fontWeight: 500 }}>{svc.label}</span>
          <span style={{ fontSize: 12, fontWeight: 600, color }}>{STATUS_LABEL[svc.status]}{svc.latency_ms != null ? ` · ${svc.latency_ms}ms` : ""}</span>
        </div>
        {svc.detail && <p style={{ fontSize: 11, color: "var(--color-danger)", margin: 0 }}>{svc.detail}</p>}
      </div>
    </div>
  );
}

function APIHealthPanel() {
  const { data, isLoading, dataUpdatedAt, refetch, isFetching } = useQuery<HealthReport>({
    queryKey: ["api-health"],
    queryFn: () => apiClient.getApiHealth(),
    refetchInterval: 60_000,
    retry: false,
  });
  const checkedAt = dataUpdatedAt ? formatDistanceToNow(new Date(dataUpdatedAt), { addSuffix: true }) : null;
  return (
    <div className="card" style={{ padding: 20, marginBottom: 24, maxWidth: 560 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0, display: "flex", alignItems: "center", gap: 6 }}>
            <Activity size={14} /> Research Source Health
          </h2>
          {checkedAt && <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 3 }}>Last checked {checkedAt} · includes NewsAPI, Google News RSS, and other external services</p>}
        </div>
        <button onClick={() => refetch()} disabled={isFetching} className="btn-secondary" style={{ padding: "5px 10px", fontSize: 12 }}>
          <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} /> {isFetching ? "Checking…" : "Refresh"}
        </button>
      </div>
      {isLoading && <div style={{ padding: 24, textAlign: "center" }}><Loader2 size={18} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} /></div>}
      {data && data.services.map(svc => <ServiceRow key={svc.name} svc={svc} />)}
    </div>
  );
}

// ── Agent Manual Panel ───────────────────────────────────────────────────────

function AgentManualPanel() {
  const [busy, setBusy] = useState<"markdown" | "pdf" | null>(null);
  const [error, setError] = useState("");

  const fetchManual = async (): Promise<string> => {
    setError("");
    return apiClient.getAgentManualMarkdown();
  };

  const handleMarkdown = async () => {
    setBusy("markdown");
    try {
      downloadAgentManualMarkdown(await fetchManual());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download the agent manual.");
    } finally {
      setBusy(null);
    }
  };

  const handlePdf = async () => {
    setBusy("pdf");
    try {
      const opened = downloadAgentManualPdf(await fetchManual());
      if (!opened) setError("The browser blocked the PDF preview window. Allow popups and try again.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to prepare the PDF export.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="card" style={{ padding: 20, maxWidth: 640 }}>
      <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
        <BookOpen size={14} /> Agent Operating Manual
      </h2>
      <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, marginTop: 6, marginBottom: 16 }}>
        Export each agent&apos;s role, system prompt, model settings, structured output schema, and core run logic. Secrets and environment values are not included.
      </p>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button onClick={handleMarkdown} disabled={busy !== null} className="btn-secondary">
          {busy === "markdown" ? <Loader2 size={13} className="animate-spin" /> : <FileText size={13} />}
          Download Markdown
        </button>
        <button onClick={handlePdf} disabled={busy !== null} className="btn-secondary">
          {busy === "pdf" ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
          Download PDF
        </button>
      </div>
      {error && (
        <div style={{ marginTop: 12, padding: "8px 12px", background: "var(--color-danger-bg)", border: "0.5px solid #fecaca", borderRadius: "var(--border-radius-md)", fontSize: 12, color: "var(--color-danger)" }}>
          {error}
        </div>
      )}
    </div>
  );
}

// ── Notifications Panel ───────────────────────────────────────────────────────

const LEVEL_COLOR: Record<string, string> = {
  error:   "var(--color-danger, #dc2626)",
  warning: "#d97706",
  info:    "#16a34a",
};

function NotificationsPanel() {
  const queryClient = useQueryClient();
  const [showUnreadOnly, setShowUnreadOnly] = useState(false);
  const { data: notifications, isLoading, refetch } = useQuery({
    queryKey: ["admin-notifications", showUnreadOnly],
    queryFn: () => apiClient.getNotifications(showUnreadOnly),
    refetchInterval: 60_000,
  });
  const markReadMutation = useMutation({
    mutationFn: (id: string) => apiClient.markNotificationRead(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-notifications"] }),
  });
  const unreadCount = notifications?.filter(n => !n.is_read).length ?? 0;

  return (
    <div style={{ maxWidth: 680 }}>
      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
              <Bell size={14} /> Pipeline Notifications
              {unreadCount > 0 && (
                <span style={{ fontSize: 11, fontWeight: 600, color: "var(--color-danger)", background: "var(--color-danger-bg)", padding: "1px 6px", borderRadius: 10 }}>
                  {unreadCount} unread
                </span>
              )}
            </h2>
            <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 4 }}>Technical failures and quality gate alerts</p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer", color: "var(--color-text-secondary)" }}>
              <input type="checkbox" checked={showUnreadOnly} onChange={e => setShowUnreadOnly(e.target.checked)} style={{ accentColor: "var(--color-action)" }} />
              Unread only
            </label>
            <button onClick={() => refetch()} className="btn-secondary" style={{ padding: "5px 10px", fontSize: 12 }}>
              <RefreshCw size={11} /> Refresh
            </button>
          </div>
        </div>
      </div>

      {isLoading && <div style={{ padding: 32, textAlign: "center" }}><Loader2 size={18} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} /></div>}

      {!isLoading && (!notifications || notifications.length === 0) && (
        <div style={{ textAlign: "center", padding: "48px 0", color: "var(--color-text-tertiary)", fontSize: 13 }}>
          <Bell size={28} style={{ margin: "0 auto 10px", opacity: 0.4 }} />
          <p>No notifications</p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {(notifications ?? []).map((n: AdminNotification) => (
          <div key={n.id} className="card" style={{ padding: "14px 16px", opacity: n.is_read ? 0.7 : 1, borderColor: n.is_read ? undefined : LEVEL_COLOR[n.level] }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: LEVEL_COLOR[n.level], textTransform: "uppercase" }}>{n.level}</span>
                  {!n.is_read && <span style={{ width: 6, height: 6, borderRadius: "50%", background: LEVEL_COLOR[n.level] }} />}
                  <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginLeft: "auto" }}>{formatDistanceToNow(new Date(n.created_at), { addSuffix: true })}</span>
                </div>
                <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>{n.title}</p>
                <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{n.message}</p>
                {n.technical_detail && (
                  <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6, fontFamily: "monospace", background: "var(--color-background-tertiary)", padding: "6px 8px", borderRadius: 6, whiteSpace: "pre-wrap" }}>{n.technical_detail}</p>
                )}
                {n.suggested_fix && (
                  <div style={{ marginTop: 8, padding: "8px 10px", background: "#f0fdf4", border: "0.5px solid #86efac", borderRadius: 6 }}>
                    <p style={{ fontSize: 11, fontWeight: 600, color: "#16a34a", marginBottom: 2 }}>Suggested fix</p>
                    <p style={{ fontSize: 11, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>{n.suggested_fix}</p>
                  </div>
                )}
              </div>
              {!n.is_read && (
                <button onClick={() => markReadMutation.mutate(n.id)} disabled={markReadMutation.isPending} className="btn-secondary" style={{ fontSize: 11, padding: "4px 8px", flexShrink: 0 }}>
                  Mark read
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminConsolePage() {
  const currentUser = getUserInfo();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("users");

  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");

  const { data: users, isLoading: usersLoading, isError: usersError } = useQuery({
    queryKey: ["admin-users"],
    queryFn: (): Promise<AdminUser[]> => apiClient.adminListUsers(),
    retry: false,
  });

  const createMutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      apiClient.adminCreateUser(email, password),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      setNewEmail(""); setNewPassword("");
      setFormError("");
      setFormSuccess("User created. They will be prompted to set a new password on first login.");
      setTimeout(() => setFormSuccess(""), 4000);
    },
    onError: (err: Error) => { setFormError(err.message); setFormSuccess(""); },
  });

  const deleteMutation = useMutation({
    mutationFn: (userId: string) => apiClient.adminDeleteUser(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(""); setFormSuccess("");
    if (newPassword.length < 8) { setFormError("Password must be at least 8 characters"); return; }
    createMutation.mutate({ email: newEmail, password: newPassword });
  };

  if (!currentUser?.is_admin) return null;

  const TAB_STYLE = (active: boolean): React.CSSProperties => ({
    padding: "6px 16px",
    borderRadius: 6,
    border: "none",
    fontSize: 13,
    fontWeight: active ? 500 : 400,
    background: active ? "var(--color-background-primary)" : "transparent",
    color: active ? "var(--color-text-primary)" : "var(--color-text-secondary)",
    cursor: "pointer",
    fontFamily: "var(--font-sans)",
    boxShadow: active ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
  });

  return (
    <div style={{ padding: "32px 40px", maxWidth: 860, margin: "0 auto" }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
        <ShieldCheck size={20} style={{ color: "var(--color-action)" }} />
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>Admin Console</h1>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, padding: 3, background: "var(--color-background-secondary)", borderRadius: 10, marginBottom: 24, width: "fit-content" }}>
        <button style={TAB_STYLE(tab === "users")}         onClick={() => setTab("users")}>User Management</button>
        <button style={TAB_STYLE(tab === "manual")}        onClick={() => setTab("manual")}>Agent Manual</button>
        <button style={TAB_STYLE(tab === "health")}        onClick={() => setTab("health")}>API Health</button>
        <button style={TAB_STYLE(tab === "notifications")} onClick={() => setTab("notifications")}>Notifications</button>
      </div>

      {/* ── USERS TAB ─────────────────────────────────────────────────────────── */}
      {tab === "users" && (
        <>
          {/* Create User */}
          <div className="card" style={{ padding: 20, marginBottom: 24 }}>
            <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16, display: "flex", alignItems: "center", gap: 6 }}>
              <UserPlus size={14} /> Add User
            </h2>
            <form onSubmit={handleCreate} style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div style={{ flex: "1 1 200px" }}>
                <label style={{ display: "block", fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 6 }}>Email</label>
                <input type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="user@example.com" required className="input" />
              </div>
              <div style={{ flex: "1 1 180px" }}>
                <label style={{ display: "block", fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 6 }}>Temporary password</label>
                <input type="text" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="Min. 8 characters" required minLength={8} className="input" style={{ fontFamily: "monospace" }} />
              </div>
              <button type="submit" disabled={createMutation.isPending} className="btn-primary" style={{ whiteSpace: "nowrap", flexShrink: 0 }}>
                {createMutation.isPending ? <><Loader2 size={13} className="animate-spin" /> Creating…</> : "Create user"}
              </button>
            </form>
            {formError && <div style={{ marginTop: 12, padding: "8px 12px", background: "var(--color-danger-bg)", border: "0.5px solid #fecaca", borderRadius: "var(--border-radius-md)", fontSize: 12, color: "var(--color-danger)" }}>{formError}</div>}
            {formSuccess && <div style={{ marginTop: 12, padding: "8px 12px", background: "#f0fdf4", border: "0.5px solid #86efac", borderRadius: "var(--border-radius-md)", fontSize: 12, color: "#16a34a" }}>{formSuccess}</div>}
          </div>

          {/* User List */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px", borderBottom: "0.5px solid var(--color-border-tertiary)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Users {users ? `(${users.length})` : ""}</h2>
              <button onClick={() => qc.invalidateQueries({ queryKey: ["admin-users"] })} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-secondary)", display: "flex", alignItems: "center", gap: 4, fontSize: 12, fontFamily: "var(--font-sans)" }}>
                <RefreshCw size={13} /> Refresh
              </button>
            </div>
            {usersLoading && <div style={{ padding: 32, textAlign: "center" }}><Loader2 size={18} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} /></div>}
            {usersError && <div style={{ padding: 24, textAlign: "center", fontSize: 13, color: "var(--color-danger)" }}>Failed to load users.</div>}
            {users && users.length === 0 && <div style={{ padding: 24, textAlign: "center", fontSize: 13, color: "var(--color-text-tertiary)" }}>No users yet.</div>}
            {users && users.length > 0 && (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
                    {["Email", "Role", "Status", "Created", ""].map(h => (
                      <th key={h} style={{ padding: "10px 20px", textAlign: "left", fontSize: 11, fontWeight: 500, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {users.map(u => (
                    <tr key={u.id} style={{ borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
                      <td style={{ padding: "12px 20px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          {u.email}
                          {u.must_change_password && <span style={{ fontSize: 10, padding: "2px 6px", background: "#fef9c3", color: "#854d0e", borderRadius: 4, fontWeight: 500 }}>pwd reset</span>}
                        </div>
                      </td>
                      <td style={{ padding: "12px 20px" }}>
                        {u.is_admin
                          ? <span style={{ fontSize: 11, padding: "2px 8px", background: "#eff6ff", color: "#2563eb", borderRadius: 4, fontWeight: 500 }}>Admin</span>
                          : <span style={{ fontSize: 11, padding: "2px 8px", background: "var(--color-background-secondary)", color: "var(--color-text-secondary)", borderRadius: 4 }}>User</span>}
                      </td>
                      <td style={{ padding: "12px 20px" }}>
                        <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 4, fontWeight: 500, background: u.is_active ? "#f0fdf4" : "var(--color-danger-bg)", color: u.is_active ? "#16a34a" : "var(--color-danger)" }}>
                          {u.is_active ? "Active" : "Disabled"}
                        </span>
                      </td>
                      <td style={{ padding: "12px 20px", color: "var(--color-text-secondary)" }}>{new Date(u.created_at).toLocaleDateString()}</td>
                      <td style={{ padding: "12px 20px", textAlign: "right" }}>
                        {u.id !== currentUser?.id && (
                          <button
                            onClick={() => { if (confirm(`Delete user ${u.email}?`)) deleteMutation.mutate(u.id); }}
                            disabled={deleteMutation.isPending}
                            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-tertiary)", display: "inline-flex", alignItems: "center", padding: 4, borderRadius: 4 }}
                            title="Delete user"
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {/* ── AGENT MANUAL TAB ─────────────────────────────────────────────────── */}
      {tab === "manual" && <AgentManualPanel />}

      {/* ── API HEALTH TAB ────────────────────────────────────────────────────── */}
      {tab === "health" && <APIHealthPanel />}

      {/* ── NOTIFICATIONS TAB ────────────────────────────────────────────────── */}
      {tab === "notifications" && <NotificationsPanel />}
    </div>
  );
}
