"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, UserPlus, ShieldCheck, RefreshCw, Database, AlertTriangle } from "lucide-react";
import { format, formatDistanceToNow } from "date-fns";
import { apiClient, type BenchmarkAdminStatus } from "@/lib/api";
import { getUserInfo } from "@/lib/auth";

type AdminUser = {
  id: string;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  must_change_password: boolean;
  created_at: string;
};

type Tab = "users" | "corpus";

function formatTs(value: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  return `${format(d, "MMM d, yyyy · HH:mm")} (${formatDistanceToNow(d, { addSuffix: true })})`;
}

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

  // ── Corpus tab ──────────────────────────────────────────────────────────────
  const corpusQuery = useQuery<BenchmarkAdminStatus>({
    queryKey: ["benchmark-status"],
    queryFn: () => apiClient.getBenchmarkStatus(),
    refetchInterval: 10_000,
  });

  const rebuildMutation = useMutation({
    mutationFn: () => apiClient.rebuildBenchmarkLibrary("combined"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benchmark-status"] }),
  });

  const corpus = corpusQuery.data;
  const buildBusy = corpus?.build_in_progress || rebuildMutation.isPending;
  const combinedCorpus = corpus?.libraries.find((library) => library.key === "combined");
  const corpusReady = Boolean(combinedCorpus?.ready_for_scoring);

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
        <button style={TAB_STYLE(tab === "users")} onClick={() => setTab("users")}>Users</button>
        <button style={TAB_STYLE(tab === "corpus")} onClick={() => setTab("corpus")}>Corpus</button>
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

      {/* ── CORPUS TAB ────────────────────────────────────────────────────────── */}
      {tab === "corpus" && (
        <>
          {/* Rebuild card */}
          <div className="card" style={{ padding: 20, marginBottom: 24 }}>
            <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
              <Database size={14} /> Corpus Rebuild
            </h2>
            <p style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7, marginBottom: 16 }}>
              Refreshes up to 25% of each healthy benchmark corpus with the newest usable videos from Business Insider, CNBC Make It, Vox, and Johnny Harris. Missing or underbuilt corpora still run a full build. Runs in the background — status updates every 10 seconds.
            </p>

            {corpusQuery.isLoading ? (
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--color-text-secondary)", fontSize: 13 }}>
                <Loader2 size={14} className="animate-spin" /> Loading corpus status…
              </div>
            ) : (
              <>
                {/* Status row */}
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
                  <span className={`badge ${corpus?.build_in_progress || !corpusReady ? "badge-warning" : "badge-success"}`}>
                    {corpus?.build_in_progress
                      ? <><Loader2 size={11} className="animate-spin" /> Rebuild running</>
                      : corpusReady
                      ? "Ready"
                      : "Needs rebuild"}
                  </span>
                  {corpus?.last_build_finished_at && (
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                      Last built: {formatTs(corpus.last_build_finished_at)}
                    </span>
                  )}
                  {!corpus?.last_build_finished_at && !corpus?.build_in_progress && (
                    <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>No build completed yet</span>
                  )}
                </div>

                <button
                  onClick={() => rebuildMutation.mutate()}
                  className="btn-primary"
                  disabled={buildBusy}
                >
                  {buildBusy ? <><Loader2 size={13} className="animate-spin" /> {corpus?.build_in_progress ? "Running…" : "Starting…"}</> : <><RefreshCw size={13} /> Refresh benchmark corpus</>}
                </button>

                {rebuildMutation.isSuccess && !corpus?.build_in_progress && (
                  <p style={{ fontSize: 12, color: "#16a34a", marginTop: 10 }}>Benchmark refresh started in the background.</p>
                )}
                {rebuildMutation.isError && (
                  <p style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 10 }}>{(rebuildMutation.error as Error).message}</p>
                )}

                {corpus?.last_build_error && (
                  <div style={{ marginTop: 14, padding: "12px 14px", borderRadius: 10, background: "var(--color-danger-bg)" }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                      <AlertTriangle size={13} style={{ color: "var(--color-danger)", flexShrink: 0, marginTop: 1 }} />
                      <div>
                        <p style={{ fontSize: 12, fontWeight: 500, color: "var(--color-danger)", marginBottom: 4 }}>Last rebuild failed</p>
                        <p style={{ fontSize: 12, color: "var(--color-danger)", lineHeight: 1.6 }}>{corpus.last_build_error}</p>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Per-library status */}
          {corpus?.libraries && corpus.libraries.length > 0 && (
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "16px 20px", borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
                <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Library Status</h2>
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
                    {["Library", "Docs", "Version", "Built", "Health"].map(h => (
                      <th key={h} style={{ padding: "10px 20px", textAlign: "left", fontSize: 11, fontWeight: 500, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {corpus.libraries.map((lib, i) => (
                    <tr key={lib.key} style={{ borderBottom: i < corpus.libraries.length - 1 ? "0.5px solid var(--color-border-tertiary)" : "none" }}>
                      <td style={{ padding: "12px 20px" }}>
                        <div style={{ fontWeight: 500 }}>{lib.label}</div>
                        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>{lib.key}</div>
                      </td>
                      <td style={{ padding: "12px 20px", color: "var(--color-text-secondary)" }}>{lib.doc_count} / {lib.minimum_doc_count} min</td>
                      <td style={{ padding: "12px 20px", color: "var(--color-text-secondary)" }}>{lib.version != null ? `v${lib.version}` : "—"}</td>
                      <td style={{ padding: "12px 20px", color: "var(--color-text-secondary)", fontSize: 12 }}>{formatTs(lib.built_at)}</td>
                      <td style={{ padding: "12px 20px" }}>
                        {!lib.implemented ? <span className="badge badge-neutral">Planned</span>
                          : !lib.available ? <span className="badge badge-danger">Unavailable</span>
                          : lib.stale ? <span className="badge badge-warning">Stale</span>
                          : <span className="badge badge-success">Healthy</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
