"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, KeyRound } from "lucide-react";
import { apiClient } from "@/lib/api";
import { getUserInfo, setUserInfo } from "@/lib/auth";

export default function ChangePasswordPage() {
  const router = useRouter();
  const user = getUserInfo();
  const isForced = user?.must_change_password ?? false;

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [error, setError] = useState("");

  const handleSkip = async () => {
    setSkipping(true);
    try {
      await apiClient.dismissPasswordChange();
      if (user) setUserInfo({ ...user, must_change_password: false });
      router.replace("/");
    } catch {
      router.replace("/");
    } finally {
      setSkipping(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match");
      return;
    }
    if (newPassword.length < 8) {
      setError("New password must be at least 8 characters");
      return;
    }
    setLoading(true);
    try {
      await apiClient.changePassword(currentPassword, newPassword);
      if (user) setUserInfo({ ...user, must_change_password: false });
      router.replace("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--color-background-tertiary)",
        padding: "24px",
      }}
    >
      <div style={{ width: "100%", maxWidth: 360 }}>

        <div style={{ marginBottom: 32, textAlign: "center" }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 36,
              height: 36,
              background: "var(--color-action)",
              borderRadius: 8,
              marginBottom: 12,
            }}
          >
            <KeyRound size={16} color="#fff" />
          </div>
          <h1 style={{ fontSize: 18, fontWeight: 500, marginBottom: 4 }}>
            {isForced ? "Change your password" : "Change password"}
          </h1>
          <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
            {isForced
              ? "Your account was set up with a temporary password."
              : "Update your account password."}
          </p>
        </div>

        <div className="card" style={{ padding: "20px" }}>
          <form onSubmit={handleSubmit}>
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

            <div style={{ marginBottom: error ? 14 : 20 }}>
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

            {error && (
              <div
                style={{
                  marginBottom: 16,
                  padding: "10px 12px",
                  background: "var(--color-danger-bg)",
                  border: "0.5px solid #fecaca",
                  borderRadius: "var(--border-radius-md)",
                  fontSize: 12,
                  color: "var(--color-danger)",
                }}
              >
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-primary" style={{ width: "100%" }}>
              {loading && <Loader2 size={14} className="animate-spin" />}
              Update password
            </button>
          </form>

          <button
            type="button"
            onClick={isForced ? handleSkip : () => router.back()}
            disabled={loading || skipping}
            style={{
              width: "100%",
              marginTop: 8,
              padding: "8px",
              border: "none",
              background: "none",
              fontSize: 13,
              color: "var(--color-text-secondary)",
              cursor: "pointer",
              fontFamily: "var(--font-sans)",
            }}
          >
            {skipping ? <Loader2 size={13} className="animate-spin" style={{ display: "inline", marginRight: 6 }} /> : null}
            {isForced ? "Skip for now — I'll change it later" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
