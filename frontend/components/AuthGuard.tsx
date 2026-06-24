"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isAuthenticated, getUserInfo } from "@/lib/auth";

const PUBLIC_PATHS = ["/login", "/register"];

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setReady(false);
    // TEMP-FIGMA-CAPTURE: bypass auth + inject a real token so data pages can fetch.
    const capToken = process.env.NEXT_PUBLIC_CAPTURE_TOKEN;
    if (capToken) {
      localStorage.setItem("ai_journalist_token", capToken);
      const capUser = process.env.NEXT_PUBLIC_CAPTURE_USER;
      if (capUser) localStorage.setItem("ai_journalist_user", capUser);
      setReady(true);
      return;
    }
    if (PUBLIC_PATHS.includes(pathname)) {
      setReady(true);
      return;
    }
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    const user = getUserInfo();
    if (user?.must_change_password && !user.is_admin && pathname !== "/change-password") {
      router.replace("/change-password");
      return;
    }
    setReady(true);
  }, [pathname, router]);

  if (!ready) return null;
  return <>{children}</>;
}
