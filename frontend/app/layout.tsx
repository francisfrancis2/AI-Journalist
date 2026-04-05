import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "AI Journalist",
  description:
    "Autonomous documentary research and scriptwriting powered by LangGraph and Claude.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.className} h-full bg-gray-950 text-gray-100`}>
        <Providers>
          <div className="flex flex-col min-h-full">
            {/* ── Top Navigation ── */}
            <header className="border-b border-gray-800 bg-gray-900/80 backdrop-blur sticky top-0 z-50">
              <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
                    <span className="text-white font-bold text-sm">AI</span>
                  </div>
                  <span className="font-semibold text-lg tracking-tight">AI Journalist</span>
                </div>
                <nav className="flex items-center gap-6 text-sm text-gray-400">
                  <a href="/" className="hover:text-white transition-colors">
                    Dashboard
                  </a>
                  <a href="/stories" className="hover:text-white transition-colors">
                    Stories
                  </a>
                  <a
                    href="/docs"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-white transition-colors"
                  >
                    API Docs
                  </a>
                </nav>
              </div>
            </header>

            {/* ── Main Content ── */}
            <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8">
              {children}
            </main>

            {/* ── Footer ── */}
            <footer className="border-t border-gray-800 mt-auto">
              <div className="max-w-7xl mx-auto px-4 py-4 text-center text-xs text-gray-600">
                AI Journalist — Powered by LangGraph + Claude claude-opus-4-6
              </div>
            </footer>
          </div>
        </Providers>
      </body>
    </html>
  );
}
