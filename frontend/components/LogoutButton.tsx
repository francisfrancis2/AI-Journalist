"use client";

import { usePathname, useRouter } from "next/navigation";
import { removeToken, isAuthenticated } from "@/lib/auth";

const PUBLIC_PATHS = ["/login", "/register"];

export function LogoutButton() {
  const router = useRouter();
  const pathname = usePathname();

  if (PUBLIC_PATHS.includes(pathname) || !isAuthenticated()) return null;

  const handleLogout = () => {
    removeToken();
    router.push("/login");
  };

  return (
    <button
      onClick={handleLogout}
      className="text-[color:var(--palette-muted)] hover:text-[color:var(--palette-primary)] transition-colors"
    >
      Sign out
    </button>
  );
}
