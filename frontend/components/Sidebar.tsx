"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FilePen, Clock, LogOut } from "lucide-react";
import { removeToken } from "@/lib/auth";

const NAV = [
  { href: "/",        label: "New Story", icon: FilePen },
  { href: "/history", label: "History",   icon: Clock },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  const handleLogout = () => {
    removeToken();
    router.replace("/login");
  };

  return (
    <aside
      style={{
        position: "fixed",
        inset: "0 auto 0 0",
        width: "var(--sidebar-w)",
        display: "flex",
        flexDirection: "column",
        background: "var(--color-background-primary)",
        borderRight: "0.5px solid var(--color-border-tertiary)",
        zIndex: 40,
      }}
    >
      {/* Logo */}
      <div
        style={{
          height: 52,
          display: "flex",
          alignItems: "center",
          padding: "0 14px",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
          gap: 8,
        }}
      >
        <div
          style={{
            width: 22,
            height: 22,
            background: "var(--color-action)",
            borderRadius: 6,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
            <path d="M2 2h3v8H2zM7 2h3v4H7zM7 8h3v2H7z" fill="#fff" />
          </svg>
        </div>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)" }}>
          AI Journalist
        </span>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, overflowY: "auto", padding: "10px 8px" }}>
        <div style={{ marginBottom: 4 }}>
          <p
            style={{
              fontSize: 11,
              fontWeight: 500,
              color: "var(--color-text-tertiary)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              padding: "6px 10px 8px",
            }}
          >
            Workspace
          </p>
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <Link key={href} href={href} className={`nav-item ${active ? "active" : ""}`}>
                <Icon size={15} />
                {label}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Footer */}
      <div style={{ padding: "8px 8px 12px", borderTop: "0.5px solid var(--color-border-tertiary)" }}>
        <button onClick={handleLogout} className="nav-item" style={{ width: "100%", border: "none", background: "none" }}>
          <LogOut size={15} />
          Sign out
        </button>
      </div>
    </aside>
  );
}
