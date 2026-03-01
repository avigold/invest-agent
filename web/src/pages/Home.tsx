import { useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useUser } from "@/lib/auth";

export default function Home() {
  const { user, loading } = useUser();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && user) {
      navigate("/dashboard", { replace: true });
    }
  }, [user, loading, navigate]);

  if (loading) return null;

  return (
    <>
      {/* Hero */}
      <section
        className="relative overflow-hidden"
        style={{ minHeight: "92vh", background: "#040a18" }}
      >
        {/* Dot-grid texture */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage:
              "radial-gradient(rgba(255,255,255,0.035) 1px, transparent 1px)",
            backgroundSize: "30px 30px",
          }}
        />

        {/* Blue glow — upper left */}
        <div
          className="absolute pointer-events-none"
          style={{
            top: "-220px",
            left: "-180px",
            width: "950px",
            height: "800px",
            background:
              "radial-gradient(ellipse, rgba(59,130,246,0.12) 0%, transparent 55%)",
            borderRadius: "50%",
          }}
        />

        {/* Subtle teal tint — lower right */}
        <div
          className="absolute pointer-events-none"
          style={{
            bottom: "-160px",
            right: "-120px",
            width: "750px",
            height: "650px",
            background:
              "radial-gradient(ellipse, rgba(20,184,166,0.06) 0%, transparent 55%)",
            borderRadius: "50%",
          }}
        />

        {/* Decorative trend-line watermark (desktop only) */}
        <svg
          className="absolute pointer-events-none select-none hidden lg:block"
          style={{
            right: "4%",
            top: "50%",
            transform: "translateY(-50%)",
            opacity: 0.04,
          }}
          width="420"
          height="280"
          viewBox="0 0 420 280"
          fill="none"
          aria-hidden="true"
        >
          <polyline
            points="20,240 120,80 200,160 380,20"
            stroke="#6b7280"
            strokeWidth="6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>

        {/* Content */}
        <div
          className="relative z-10 flex flex-col items-center justify-center text-center px-6"
          style={{ minHeight: "92vh", paddingTop: "6rem", paddingBottom: "6rem" }}
        >
          <p className="text-brand text-xs font-mono uppercase tracking-widest mb-6 select-none">
            Automated Investment Research
          </p>

          <h1
            className="font-bold tracking-tight text-white mb-6"
            style={{
              fontSize: "clamp(2.6rem, 7.5vw, 5.5rem)",
              lineHeight: 1.07,
              maxWidth: "16ch",
            }}
          >
            Research smarter.
            <br />
            <span className="text-brand">Decide faster.</span>
          </h1>

          <p
            className="text-gray-400 leading-relaxed mb-10"
            style={{ fontSize: "1.125rem", maxWidth: "40ch" }}
          >
            Ingest macro, industry, and company data. Compute deterministic
            scores with full evidence lineage. Make better investment decisions.
          </p>

          <Link
            to="/login"
            className="inline-flex items-center justify-center gap-2 font-bold text-white px-8 py-3.5 rounded-md text-base transition-all"
            style={{
              background: "#3b82f6",
              boxShadow: "0 0 0 0 rgba(59,130,246,0)",
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.background = "#60a5fa";
              e.currentTarget.style.boxShadow =
                "0 0 24px rgba(59,130,246,0.3)";
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.background = "#3b82f6";
              e.currentTarget.style.boxShadow =
                "0 0 0 0 rgba(59,130,246,0)";
            }}
          >
            Get started
          </Link>

          <p className="text-gray-600 text-xs mt-4 select-none">
            Score countries, industries, and companies — all in one platform.
          </p>
        </div>

        {/* Scroll indicator */}
        <div className="absolute bottom-7 left-0 right-0 flex justify-center pointer-events-none">
          <div
            className="text-gray-700 text-xs select-none"
            style={{ animation: "bounce-arrow 2s infinite" }}
          >
            ↓
          </div>
        </div>
      </section>

      {/* Features */}
      <section
        className=""
        style={{ background: "#060e1e", borderTop: "1px solid #1a2540" }}
      >
        <div className="max-w-6xl mx-auto px-6 py-24">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold text-white mb-3">
              Three layers of analysis
            </h2>
            <p className="text-gray-500 text-base">
              Macro to micro. Scored and ranked.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div
              className="rounded-2xl border p-7 transition-all duration-200 hover:-translate-y-0.5"
              style={{
                background: "#0a1525",
                borderColor: "#1e2d45",
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.borderColor = "rgba(59,130,246,0.3)";
                e.currentTarget.style.boxShadow =
                  "0 0 0 1px rgba(59,130,246,0.06), 0 8px 32px rgba(0,0,0,0.5)";
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.borderColor = "#1e2d45";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              <svg width="32" height="32" viewBox="0 0 32 32" fill="none" className="mb-5" style={{ opacity: 0.5 }}>
                <circle cx="16" cy="16" r="12" stroke="#9ca3af" strokeWidth="1.5" />
                <ellipse cx="16" cy="16" rx="6" ry="12" stroke="#9ca3af" strokeWidth="1.5" />
                <line x1="4" y1="16" x2="28" y2="16" stroke="#9ca3af" strokeWidth="1.5" />
              </svg>
              <h3 className="text-white font-semibold text-lg mb-3">
                Country Scoring
              </h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Comprehensive macro analysis, market performance, and political
                stability — every major economy scored and ranked automatically.
              </p>
            </div>

            <div
              className="rounded-2xl border p-7 transition-all duration-200 hover:-translate-y-0.5"
              style={{
                background: "#0a1525",
                borderColor: "#1e2d45",
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.borderColor = "rgba(59,130,246,0.3)";
                e.currentTarget.style.boxShadow =
                  "0 0 0 1px rgba(59,130,246,0.06), 0 8px 32px rgba(0,0,0,0.5)";
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.borderColor = "#1e2d45";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              <svg width="32" height="32" viewBox="0 0 32 32" fill="none" className="mb-5" style={{ opacity: 0.5 }}>
                <rect x="4" y="18" width="5" height="10" rx="1" stroke="#9ca3af" strokeWidth="1.5" />
                <rect x="13.5" y="10" width="5" height="18" rx="1" stroke="#9ca3af" strokeWidth="1.5" />
                <rect x="23" y="4" width="5" height="24" rx="1" stroke="#9ca3af" strokeWidth="1.5" />
              </svg>
              <h3 className="text-white font-semibold text-lg mb-3">
                Industry Analysis
              </h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Every sector evaluated against live macro conditions in each country.
                Continuously scored so you always know where the tailwinds are.
              </p>
            </div>

            <div
              className="rounded-2xl border p-7 transition-all duration-200 hover:-translate-y-0.5"
              style={{
                background: "#0a1525",
                borderColor: "#1e2d45",
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.borderColor = "rgba(59,130,246,0.3)";
                e.currentTarget.style.boxShadow =
                  "0 0 0 1px rgba(59,130,246,0.06), 0 8px 32px rgba(0,0,0,0.5)";
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.borderColor = "#1e2d45";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              <svg width="32" height="32" viewBox="0 0 32 32" fill="none" className="mb-5" style={{ opacity: 0.5 }}>
                <polyline points="4,24 12,14 18,18 28,6" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx="28" cy="6" r="2.5" stroke="#9ca3af" strokeWidth="1.5" />
              </svg>
              <h3 className="text-white font-semibold text-lg mb-3">
                Company Scoring
              </h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Deep fundamental analysis and real-time market signals across
                hundreds of companies. Every score backed by a complete evidence chain.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section
        className=""
        style={{
          background: "#040a18",
          borderTop: "1px solid #1a2540",
          borderBottom: "1px solid #1a2540",
        }}
      >
        <div className="max-w-4xl mx-auto px-6 py-24 text-center">
          <h2 className="text-3xl font-bold text-white mb-16">
            Up and running in minutes
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-12">
            <div>
              <div className="text-3xl font-bold text-brand mb-4 font-mono">
                01
              </div>
              <h3 className="text-white font-semibold mb-2">Sign in</h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                One click with Google. No setup, no configuration files.
              </p>
            </div>

            <div>
              <div className="text-3xl font-bold text-brand mb-4 font-mono">
                02
              </div>
              <h3 className="text-white font-semibold mb-2">Run a refresh</h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Kick off country, industry, or company jobs. Data is ingested,
                scored, and packaged automatically.
              </p>
            </div>

            <div>
              <div className="text-3xl font-bold text-brand mb-4 font-mono">
                03
              </div>
              <h3 className="text-white font-semibold mb-2">Get recommendations</h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Buy, Hold, or Sell — computed from country, industry, and company
                scores with full transparency.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="text-center px-6 py-28" style={{ background: "#040a18" }}>
        <div className="relative inline-block overflow-hidden">
          <div
            className="absolute pointer-events-none"
            style={{
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              width: "500px",
              height: "300px",
              background:
                "radial-gradient(ellipse, rgba(59,130,246,0.08) 0%, transparent 65%)",
            }}
          />
          <div className="relative z-10">
            <h2 className="text-3xl md:text-4xl font-bold text-white mb-3">
              Ready to research smarter?
            </h2>
            <p className="text-gray-500 mb-10 text-base">
              Deterministic scores. Evidence-backed decisions.
            </p>
            <Link
              to="/login"
              className="inline-flex items-center justify-center font-bold text-white px-8 py-3.5 rounded-md text-base transition-all"
              style={{
                background: "#3b82f6",
                boxShadow: "0 0 0 0 rgba(59,130,246,0)",
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.background = "#60a5fa";
                e.currentTarget.style.boxShadow =
                  "0 0 28px rgba(59,130,246,0.3)";
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.background = "#3b82f6";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              Get started
            </Link>
          </div>
        </div>
      </section>

      <style>{`
        @keyframes bounce-arrow {
          0%, 100% { transform: translateY(0); opacity: 0.4; }
          50%       { transform: translateY(6px); opacity: 0.8; }
        }
      `}</style>
    </>
  );
}
