import type { Metadata } from "next";
import { Fraunces, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { AuthGuard } from "@/components/AuthGuard";
import { SidebarWrapper } from "@/components/SidebarWrapper";

const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  style: ["normal", "italic"],
  variable: "--font-fraunces",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "AI Journalist",
  description: "Autonomous documentary research and scriptwriting.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" style={{ height: "100%" }} className={`${fraunces.variable} ${jetbrains.variable}`}>
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
