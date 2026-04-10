import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { AuthGuard } from "@/components/AuthGuard";
import { SidebarWrapper } from "@/components/SidebarWrapper";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "AI Journalist",
  description: "Autonomous documentary research and scriptwriting.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" style={{ height: "100%" }}>
      <body>
        <Providers>
          <AuthGuard>
            <SidebarWrapper>
              {children}
            </SidebarWrapper>
          </AuthGuard>
        </Providers>
      </body>
    </html>
  );
}
