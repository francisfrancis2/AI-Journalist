import type { Metadata } from "next";
import { Fraunces, Inter, JetBrains_Mono } from "next/font/google";
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

// Untitled UI's UI typeface. Fraunces stays for editorial display — the kit has
// no opinion about that, and it carries the brand voice.
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-inter",
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
    <html lang="en" style={{ height: "100%" }} className={`${fraunces.variable} ${jetbrains.variable} ${inter.variable}`}>
      <body>
        {/* TEMP-FIGMA-CAPTURE */}
        <script async src="https://mcp.figma.com/mcp/html-to-design/capture.js" />
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
