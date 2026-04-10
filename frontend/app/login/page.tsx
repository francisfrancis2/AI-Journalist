"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import { setToken } from "@/lib/auth";

type Tab = "signin" | "signup";

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = tab === "signin"
        ? await apiClient.login(email, password)
        : await apiClient.register(email, password);
      setToken(res.access_token);
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

        {/* Logo mark */}
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
            <svg width="16" height="16" viewBox="0 0 12 12" fill="none">
              <path d="M2 2h3v8H2zM7 2h3v4H7zM7 8h3v2H7z" fill="#fff" />
            </svg>
          </div>
          <h1 style={{ fontSize: 18, fontWeight: 500, marginBottom: 4 }}>AI Journalist</h1>
          <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
            {tab === "signin" ? "Sign in to your workspace" : "Create your workspace"}
          </p>
        </div>

        {/* Card */}
        <div className="card" style={{ padding: "20px" }}>
          {/* Tab toggle */}
          <div
            style={{
              display: "flex",
              gap: 4,
              padding: 3,
              background: "var(--color-background-secondary)",
              borderRadius: 10,
              marginBottom: 20,
            }}
          >
            {(["signin", "signup"] as Tab[]).map(t => (
              <button
                key={t}
                onClick={() => { setTab(t); setError(""); }}
                style={{
                  flex: 1,
                  padding: "6px 0",
                  borderRadius: 8,
                  border: "none",
                  fontSize: 13,
                  fontWeight: tab === t ? 500 : 400,
                  background: tab === t ? "var(--color-background-primary)" : "transparent",
                  color: tab === t ? "var(--color-text-primary)" : "var(--color-text-secondary)",
                  cursor: "pointer",
                  transition: "all 0.12s",
                  boxShadow: tab === t ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
                  fontFamily: "var(--font-sans)",
                }}
              >
                {t === "signin" ? "Sign in" : "Sign up"}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 14 }}>
              <label
                style={{
                  display: "block",
                  fontSize: 12,
                  color: "var(--color-text-secondary)",
                  marginBottom: 6,
                  fontWeight: 400,
                }}
              >
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                className="input"
              />
            </div>

            <div style={{ marginBottom: error ? 14 : 20 }}>
              <label
                style={{
                  display: "block",
                  fontSize: 12,
                  color: "var(--color-text-secondary)",
                  marginBottom: 6,
                }}
              >
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Min. 8 characters"
                required
                minLength={8}
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
              {tab === "signin" ? "Sign in" : "Create account"}
            </button>
          </form>

          <p style={{ marginTop: 16, textAlign: "center", fontSize: 12, color: "var(--color-text-tertiary)" }}>
            {tab === "signin" ? "No account? " : "Already have one? "}
            <button
              onClick={() => { setTab(tab === "signin" ? "signup" : "signin"); setError(""); }}
              style={{
                background: "none",
                border: "none",
                fontSize: 12,
                color: "var(--color-text-secondary)",
                cursor: "pointer",
                textDecoration: "underline",
                fontFamily: "var(--font-sans)",
              }}
            >
              {tab === "signin" ? "Sign up" : "Sign in"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
