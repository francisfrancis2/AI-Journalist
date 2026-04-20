"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ArrowRight, Pause, Play } from "lucide-react";
import { apiClient } from "@/lib/api";
import { setToken, setUserInfo } from "@/lib/auth";

type Quote = { text: string; author: string; role: string };

const QUOTES: Quote[] = [
  { text: "Cinema is a matter of <em>what's in the frame</em> and what's out.",
    author: "Martin Scorsese", role: "Director · 1990" },
  { text: "Film is a battleground: love, hate, action, violence, death. In one word — <em>emotion</em>.",
    author: "Samuel Fuller", role: "Director · 1965" },
  { text: "A good ending is vital to a picture — the single most important element — because it is what the audience takes with them out of the theater.",
    author: "Billy Wilder", role: "Director · 1959" },
  { text: "Every edit is a lie that tells the <em>truth</em>.",
    author: "Agnès Varda", role: "Filmmaker · 1985" },
  { text: "The role of a director is simply to be the <em>conductor</em>. The film is already there — you just have to reveal it.",
    author: "Akira Kurosawa", role: "Director · 1975" },
  { text: "Documentary is not what is, but what <em>could be</em>.",
    author: "Werner Herzog", role: "Documentary Director · 1999" },
  { text: "I don't want to express myself — I want to express the <em>world</em>.",
    author: "Frederick Wiseman", role: "Documentary Director · 1998" },
  { text: "A film is a ribbon of dreams.",
    author: "Orson Welles", role: "Director · 1958" },
  { text: "If it can be written, or thought, it can be <em>filmed</em>.",
    author: "Stanley Kubrick", role: "Director · 1972" },
  { text: "The most political thing a documentary can do is pay <em>close attention</em>.",
    author: "Laura Poitras", role: "Documentary Director · 2015" },
  { text: "To make a film is to create an organism — it must <em>breathe</em>.",
    author: "Chantal Akerman", role: "Filmmaker · 1976" },
  { text: "A documentary is not a mirror. It's a <em>hammer</em> with which to shape reality.",
    author: "Dziga Vertov", role: "Documentary Pioneer · 1923" },
  { text: "The camera is the eye of history.",
    author: "Raoul Peck", role: "Documentary Director · 2016" },
  { text: "What we do in life echoes in eternity — and <em>so does the frame</em> we put around it.",
    author: "Errol Morris", role: "Documentary Director · 2004" },
  { text: "Cinema should make you forget you are sitting in a theatre.",
    author: "Roman Polanski", role: "Director · 1970" },
];

const DUR_SEC = 7;

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const next = useCallback(() => setIdx(i => (i + 1) % QUOTES.length), []);
  const goTo = useCallback((i: number) => setIdx(i), []);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!playing) return;
    timerRef.current = setTimeout(next, DUR_SEC * 1000);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [idx, playing, next]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await apiClient.login(email, password);
      setToken(res.access_token, remember);
      const me = await apiClient.getMe();
      setUserInfo({
        id: me.id,
        email: me.email,
        is_admin: me.is_admin,
        must_change_password: me.must_change_password,
      }, remember);
      if (me.must_change_password && !me.is_admin) router.replace("/change-password");
      else router.replace("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-shell">
      <aside className="login-col">
        <header className="brand">
          <span className="brand-mark">
            <svg width="14" height="14" viewBox="0 0 12 12" fill="none">
              <path d="M2 2h3v8H2zM7 2h3v4H7zM7 8h3v2H7z" fill="#fff" />
            </svg>
          </span>
          <span className="brand-name">AI Journalist</span>
          <span className="brand-meta">v2.4 · APR 2026</span>
        </header>

        <section className="login-body">
          <div className="eyebrow">Workspace · Sign in</div>
          <h1 className="login-title">
            Every story starts with a <em>single sentence.</em>
          </h1>
          <p className="login-sub">
            Sign in to your research desk. Draft, investigate, and script long-form
            journalism with an agent that reads like a producer.
          </p>

          <form onSubmit={handleSubmit} noValidate>
            <div className="field">
              <label className="field-label" htmlFor="email">Email</label>
              <input
                id="email"
                className="input"
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@newsroom.com"
                autoComplete="email"
                required
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="password">Password</label>
              <input
                id="password"
                className="input"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••••"
                autoComplete="current-password"
                required
              />
            </div>

            <div className="row-between">
              <label className="check">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={e => setRemember(e.target.checked)}
                />
                Keep me signed in
              </label>
              <span className="access-note">Admin access required</span>
            </div>

            {error && <div className="form-error">{error}</div>}

            <button type="submit" className="btn-primary btn-full" disabled={loading}>
              {loading ? <Loader2 size={14} className="animate-spin" /> : null}
              Sign in
              {!loading && <ArrowRight size={14} />}
            </button>

            <p className="register-line">Need an account? Ask an admin to invite you.</p>
          </form>
        </section>

        <footer className="login-foot">
          <div className="brand-meta" style={{ margin: 0 }}>© 2026 AI Journalist</div>
          <div className="foot-links">
            <span>Secure workspace</span>
            <span>Editorial tools</span>
          </div>
        </footer>
      </aside>

      <section className="stage">
        <div className="stage-inner">
          <div className="stage-head">
            <div><span className="dot" /> THE WRITERS&apos; ROOM · live</div>
            <LiveClock />
          </div>

          <div className="quote-area">
            <div className="quote-stack">
              {QUOTES.map((q, i) => {
                const cls =
                  i === idx
                    ? "quote-card in"
                    : i === (idx - 1 + QUOTES.length) % QUOTES.length
                    ? "quote-card out"
                    : "quote-card";
                return (
                  <article key={i} className={cls}>
                    <div className="quote-mark" aria-hidden="true">&ldquo;</div>
                    <p
                      className="quote-text"
                      dangerouslySetInnerHTML={{ __html: q.text }}
                    />
                    <div className="quote-attr">
                      <span className="name">{q.author}</span>
                      <span className="rule" />
                      <span className="role">{q.role}</span>
                    </div>
                  </article>
                );
              })}
            </div>
          </div>

          <div className="stage-foot">
            <button
              type="button"
              className="pp"
              onClick={() => setPlaying(p => !p)}
              aria-label={playing ? "Pause" : "Play"}
            >
              {playing ? <Pause size={10} /> : <Play size={10} />}
            </button>
            <div className="progress">
              {QUOTES.map((_, i) => {
                const cls =
                  i < idx
                    ? "tick done"
                    : i === idx
                    ? `tick active${playing ? "" : " paused"}`
                    : "tick";
                return (
                  <div
                    key={i}
                    className={cls}
                    style={
                      i === idx
                        ? ({ "--dur": `${DUR_SEC * 1000}ms` } as React.CSSProperties)
                        : undefined
                    }
                    onClick={() => goTo(i)}
                  >
                    <div className="fill" key={`${i}-${idx}`} />
                  </div>
                );
              })}
            </div>
            <div className="counter">
              <b>{String(idx + 1).padStart(2, "0")}</b>&nbsp;/&nbsp;
              {String(QUOTES.length).padStart(2, "0")}
            </div>
          </div>
        </div>
      </section>

      <style jsx>{`
        .login-shell {
          display: grid;
          grid-template-columns: minmax(420px, 1fr) 1.2fr;
          height: 100vh;
          width: 100vw;
          background: var(--color-background-primary);
          --stage-bg: #0b0d1a;
          --stage-ink: #e8e6df;
          --stage-dim: #8b8a82;
          --stage-accent: #c6b77a;
          --font-serif: var(--font-fraunces), "Fraunces", Georgia, serif;
          --font-mono: var(--font-jetbrains), "JetBrains Mono", ui-monospace, monospace;
        }
        @media (max-width: 900px) {
          .login-shell { grid-template-columns: 1fr; }
          .stage { display: none; }
        }

        .login-col {
          position: relative;
          display: flex;
          flex-direction: column;
          padding: 28px 40px;
          background: var(--color-background-primary);
          border-right: 0.5px solid var(--color-border-tertiary);
          overflow: hidden;
        }
        .brand { display: flex; align-items: center; gap: 10px; }
        .brand-mark {
          width: 26px; height: 26px;
          background: var(--color-action);
          border-radius: 6px;
          display: inline-flex; align-items: center; justify-content: center;
        }
        .brand-name { font-size: 13px; font-weight: 500; color: var(--color-text-primary); }
        .brand-meta {
          margin-left: auto;
          font-family: var(--font-mono);
          font-size: 10.5px;
          letter-spacing: 0.04em;
          color: var(--color-text-tertiary);
          text-transform: uppercase;
        }

        .login-body { margin: auto 0; width: 100%; max-width: 360px; }
        .eyebrow {
          font-family: var(--font-mono);
          font-size: 10.5px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--color-text-tertiary);
          margin-bottom: 14px;
        }
        .login-title {
          font-family: var(--font-serif);
          font-weight: 300;
          font-size: 34px;
          line-height: 1.08;
          letter-spacing: -0.015em;
          color: var(--color-text-primary);
          margin: 0 0 10px;
        }
        .login-title em { font-style: italic; color: var(--color-action); font-weight: 400; }
        .login-sub {
          font-size: 13px;
          color: var(--color-text-secondary);
          margin: 0 0 28px;
          max-width: 32ch;
          text-wrap: pretty;
        }

        .field { margin-bottom: 14px; }
        .field-label {
          display: block;
          font-size: 11px;
          font-weight: 500;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--color-text-secondary);
          margin-bottom: 6px;
        }

        .row-between {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 18px;
        }
        .check {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          font-size: 12px;
          color: var(--color-text-secondary);
          cursor: pointer;
          user-select: none;
        }
        .check input {
          appearance: none;
          width: 14px; height: 14px;
          border-radius: 3px;
          border: 0.5px solid var(--color-border-primary);
          background: var(--color-background-secondary);
          cursor: pointer;
          display: inline-grid;
          place-content: center;
          flex-shrink: 0;
        }
        .check input:checked { background: var(--color-action); border-color: var(--color-action); }
        .check input:checked::after {
          content: "";
          width: 8px; height: 8px;
          background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'><path fill='none' stroke='white' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' d='M1 4.2 3.2 6.4 7 1.8'/></svg>");
          background-size: contain;
          background-repeat: no-repeat;
        }
        .access-note { font-size: 12px; color: var(--color-text-tertiary); white-space: nowrap; }

        .btn-full { width: 100%; padding: 11px 20px; }

        .form-error {
          margin-bottom: 14px;
          padding: 10px 12px;
          background: var(--color-danger-bg);
          border: 0.5px solid #fecaca;
          border-radius: var(--border-radius-md);
          font-size: 12px;
          color: var(--color-danger);
        }

        .register-line {
          font-size: 12.5px;
          color: var(--color-text-secondary);
          margin-top: 20px;
          text-align: center;
        }

        .login-foot {
          margin-top: auto;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          padding-top: 18px;
        }
        .foot-links { display: flex; gap: 14px; }
        .foot-links span { font-size: 11.5px; color: var(--color-text-tertiary); }

        .stage {
          position: relative;
          background: var(--stage-bg);
          color: var(--stage-ink);
          overflow: hidden;
          isolation: isolate;
        }
        .stage::before {
          content: "";
          position: absolute; inset: 0;
          background:
            radial-gradient(60% 50% at 70% 30%, rgba(28, 38, 168, 0.35) 0%, rgba(28, 38, 168, 0) 60%),
            radial-gradient(80% 60% at 20% 90%, rgba(198, 183, 122, 0.12) 0%, rgba(198, 183, 122, 0) 65%),
            linear-gradient(180deg, #0b0d1a 0%, #070814 100%);
          z-index: 0;
        }
        .stage::after {
          content: "";
          position: absolute; inset: 0;
          background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160' viewBox='0 0 160 160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.35 0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)' opacity='0.5'/></svg>");
          mix-blend-mode: overlay;
          opacity: 0.25;
          z-index: 1;
          pointer-events: none;
        }
        .stage-inner {
          position: absolute;
          inset: 0;
          display: grid;
          grid-template-rows: auto 1fr auto;
          padding: 28px 48px 28px 56px;
          z-index: 2;
        }

        .stage-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          color: var(--stage-dim);
          font-family: var(--font-mono);
          font-size: 10.5px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
        }
        .dot {
          display: inline-block;
          width: 6px; height: 6px;
          border-radius: 50%;
          background: var(--stage-accent);
          margin-right: 8px;
          vertical-align: middle;
          box-shadow: 0 0 10px rgba(198, 183, 122, 0.65);
          animation: pulse 2.8s ease-in-out infinite;
        }
        @keyframes pulse {
          0%, 100% { opacity: 0.5; transform: scale(1); }
          50%       { opacity: 1;   transform: scale(1.15); }
        }

        .quote-area { position: relative; display: flex; align-items: center; min-height: 0; }
        .quote-stack { position: relative; width: 100%; max-width: 620px; min-height: 320px; }
        .quote-card {
          position: absolute;
          inset: 0;
          display: flex;
          flex-direction: column;
          justify-content: center;
          opacity: 0;
          transform: translateY(18px);
          transition: opacity 1.1s ease, transform 1.1s ease, filter 1.1s ease;
          filter: blur(6px);
          pointer-events: none;
        }
        .quote-card.in  { opacity: 1; transform: translateY(0);    filter: blur(0); }
        .quote-card.out { opacity: 0; transform: translateY(-18px); filter: blur(6px); }

        .quote-mark {
          font-family: var(--font-serif);
          font-style: italic;
          font-weight: 300;
          font-size: 120px;
          line-height: 0.7;
          color: var(--stage-accent);
          opacity: 0.35;
          margin-bottom: 10px;
          user-select: none;
        }
        .quote-text {
          font-family: var(--font-serif);
          font-weight: 300;
          font-size: clamp(28px, 3.2vw, 44px);
          line-height: 1.15;
          letter-spacing: -0.015em;
          color: var(--stage-ink);
          margin: 0 0 22px;
          text-wrap: balance;
        }
        .quote-text :global(em) { font-style: italic; color: var(--stage-accent); }
        .quote-attr { display: flex; align-items: baseline; gap: 14px; }
        .quote-attr .name { font-size: 13.5px; font-weight: 500; color: var(--stage-ink); }
        .quote-attr .role {
          font-family: var(--font-mono);
          font-size: 10.5px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--stage-dim);
        }
        .quote-attr .rule {
          display: inline-block;
          width: 24px;
          height: 0.5px;
          background: var(--stage-dim);
          transform: translateY(-3px);
        }

        .stage-foot { display: flex; align-items: center; color: var(--stage-dim); gap: 20px; }
        .pp {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 28px; height: 28px;
          border-radius: 50%;
          border: 0.5px solid rgba(232, 230, 223, 0.25);
          background: transparent;
          color: var(--stage-ink);
          cursor: pointer;
          transition: border-color 0.15s, background 0.15s;
        }
        .pp:hover { border-color: rgba(232, 230, 223, 0.6); background: rgba(232, 230, 223, 0.05); }
        .progress { flex: 1; display: flex; gap: 6px; align-items: center; }
        .tick {
          flex: 1;
          height: 1px;
          background: rgba(232, 230, 223, 0.15);
          position: relative;
          overflow: hidden;
          cursor: pointer;
        }
        .tick .fill { position: absolute; inset: 0; width: 0%; background: var(--stage-ink); }
        .tick.done .fill { width: 100%; }
        .tick.active .fill { animation: fillup var(--dur, 7000ms) linear forwards; }
        .tick.active.paused .fill { animation-play-state: paused; }
        @keyframes fillup { to { width: 100%; } }

        .counter {
          font-family: var(--font-mono);
          font-size: 10.5px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          min-width: 52px;
          text-align: right;
        }
        .counter b { color: var(--stage-ink); font-weight: 500; }
      `}</style>
    </div>
  );
}

function LiveClock() {
  const [t, setT] = useState<string>("");
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const hh = String(d.getHours()).padStart(2, "0");
      const mm = String(d.getMinutes()).padStart(2, "0");
      const ss = String(d.getSeconds()).padStart(2, "0");
      const tz = -d.getTimezoneOffset() / 60;
      setT(`${hh}:${mm}:${ss} GMT${tz >= 0 ? "+" : ""}${tz}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return <div suppressHydrationWarning>{t || "—"}</div>;
}
