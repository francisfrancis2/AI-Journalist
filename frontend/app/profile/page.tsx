"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, User, KeyRound, ShieldCheck, Calendar, Mail } from "lucide-react";
import { apiClient } from "@/lib/api";
import { setUserInfo, getUserInfo } from "@/lib/auth";

export default function ProfilePage() {
  const storedUser = getUserInfo();

  const { data: me, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: () => apiClient.getMe(),
  });

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pwLoading, setPwLoading] = useState(false);
  const [pwError, setPwError] = useState("");
  const [pwSuccess, setPwSuccess] = useState("");

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwError("");
    setPwSuccess("");
    if (newPassword !== confirmPassword) {
      setPwError("New passwords do not match");
      return;
    }
    if (newPassword.length < 8) {
      setPwError("New password must be at least 8 characters");
      return;
    }
    setPwLoading(true);
    try {
      await apiClient.changePassword(currentPassword, newPassword);
      if (storedUser) setUserInfo({ ...storedUser, must_change_password: false });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPwSuccess("Password updated successfully.");
      setTimeout(() => setPwSuccess(""), 4000);
    } catch (err: unknown) {
      setPwError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setPwLoading(false);
    }
  };

  const user = me ?? storedUser;

  return (
    <div style={{ padding: "32px 40px", maxWidth: 600, margin: "0 auto" }}>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 32 }}>
        <User size={20} style={{ color: "var(--color-action)" }} />
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>My Profile</h1>
      </div>

      {/* Account details */}
      <div className="card" style={{ padding: 20, marginBottom: 24 }}>
        <h2 style={{ fontSize: 13, fontWeight: 600, marginBottom: 16, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Account
        </h2>

        {isLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 16 }}>
            <Loader2 size={16} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Mail size={14} style={{ color: "var(--color-text-tertiary)", flexShrink: 0 }} />
              <div>
                <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 2 }}>Email</div>
                <div style={{ fontSize: 13, color: "var(--color-text-primary)", fontWeight: 500 }}>{user?.email ?? "—"}</div>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <ShieldCheck size={14} style={{ color: "var(--color-text-tertiary)", flexShrink: 0 }} />
              <div>
                <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 2 }}>Role</div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  {user?.is_admin ? (
                    <span style={{ fontSize: 12, padding: "2px 8px", background: "#eff6ff", color: "#2563eb", borderRadius: 4, fontWeight: 500 }}>
                      Administrator
                    </span>
                  ) : (
                    <span style={{ fontSize: 12, padding: "2px 8px", background: "var(--color-background-secondary)", color: "var(--color-text-secondary)", borderRadius: 4 }}>
                      User
                    </span>
                  )}
                </div>
              </div>
            </div>

            {me?.created_at && (
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <Calendar size={14} style={{ color: "var(--color-text-tertiary)", flexShrink: 0 }} />
                <div>
                  <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 2 }}>Member since</div>
                  <div style={{ fontSize: 13, color: "var(--color-text-primary)" }}>
                    {new Date(me.created_at).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Change password */}
      <div className="card" style={{ padding: 20 }}>
        <h2 style={{ fontSize: 13, fontWeight: 600, marginBottom: 16, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", display: "flex", alignItems: "center", gap: 6 }}>
          <KeyRound size={13} />
          Change Password
        </h2>

        <form onSubmit={handlePasswordChange}>
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 6 }}>
              Current password
            </label>
            <input
              type="password"
              value={currentPassword}
              onChange={e => setCurrentPassword(e.target.value)}
              placeholder="Your current password"
              required
              className="input"
            />
          </div>

          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 6 }}>
              New password
            </label>
            <input
              type="password"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              placeholder="Min. 8 characters"
              required
              minLength={8}
              className="input"
            />
          </div>

          <div style={{ marginBottom: pwError || pwSuccess ? 14 : 20 }}>
            <label style={{ display: "block", fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 6 }}>
              Confirm new password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              placeholder="Repeat new password"
              required
              className="input"
            />
          </div>

          {pwError && (
            <div style={{ marginBottom: 16, padding: "10px 12px", background: "var(--color-danger-bg)", border: "0.5px solid #fecaca", borderRadius: "var(--border-radius-md)", fontSize: 12, color: "var(--color-danger)" }}>
              {pwError}
            </div>
          )}
          {pwSuccess && (
            <div style={{ marginBottom: 16, padding: "10px 12px", background: "#f0fdf4", border: "0.5px solid #86efac", borderRadius: "var(--border-radius-md)", fontSize: 12, color: "#16a34a" }}>
              {pwSuccess}
            </div>
          )}

          <button type="submit" disabled={pwLoading} className="btn-primary">
            {pwLoading && <Loader2 size={14} className="animate-spin" />}
            Update password
          </button>
        </form>
      </div>
    </div>
  );
}
