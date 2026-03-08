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
            AI-Powered Investment Research
          </p>

          <h1
            className="font-bold tracking-tight text-white mb-6"
            style={{
              fontSize: "clamp(2.6rem, 7.5vw, 5.5rem)",
              lineHeight: 1.07,
              maxWidth: "18ch",
            }}
          >
            Find winners
            <br />
            <span className="text-brand">before the market does.</span>
          </h1>

          <p
            className="text-gray-400 leading-relaxed mb-10"
            style={{ fontSize: "1.125rem", maxWidth: "46ch" }}
          >
            770,000+ observations. 16,000+ companies across 24 countries.
            186 features per stock. Walk-forward backtested and
            Platt-calibrated. Every prediction evidence-backed.
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
            AI predictions, deterministic scores, and full evidence lineage — one platform.
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

      {/* ML Headline Section */}
      <section
        style={{ background: "#060e1e", borderTop: "1px solid #1a2540" }}
      >
        <div className="max-w-6xl mx-auto px-6 py-24">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold text-white mb-3">
              Machine learning meets fundamental analysis
            </h2>
            <p className="text-gray-500 text-base max-w-2xl mx-auto">
              Two independent scoring systems working together.
              The ML model learns from 770,000+ historical observations to identify
              outperformance patterns. The deterministic system provides transparent,
              evidence-backed fundamental scores.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* ML Card */}
            <FeatureCard
              icon={
                <svg width="32" height="32" viewBox="0 0 32 32" fill="none" style={{ opacity: 0.5 }}>
                  <path d="M6 26L12 14L18 18L26 6" stroke="#60a5fa" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  <circle cx="12" cy="14" r="2" stroke="#60a5fa" strokeWidth="1.5" />
                  <circle cx="18" cy="18" r="2" stroke="#60a5fa" strokeWidth="1.5" />
                  <circle cx="26" cy="6" r="2" stroke="#60a5fa" strokeWidth="1.5" />
                </svg>
              }
              title="ML Predictions"
              description="Trained on 770,000+ observations spanning 16,000+ companies across 24 countries. 186 features per stock. Walk-forward cross-validation prevents look-ahead bias. Platt-calibrated probabilities with Kelly sizing."
              stats={[
                { label: "Observations", value: "770k+" },
                { label: "Companies", value: "16,000+" },
                { label: "Features", value: "186" },
              ]}
            />

            {/* Deterministic Card */}
            <FeatureCard
              icon={
                <svg width="32" height="32" viewBox="0 0 32 32" fill="none" style={{ opacity: 0.5 }}>
                  <rect x="4" y="4" width="24" height="24" rx="3" stroke="#9ca3af" strokeWidth="1.5" />
                  <line x1="4" y1="12" x2="28" y2="12" stroke="#9ca3af" strokeWidth="1.5" />
                  <line x1="14" y1="12" x2="14" y2="28" stroke="#9ca3af" strokeWidth="1.5" />
                </svg>
              }
              title="Deterministic Scores"
              description="Transparent fundamental and market scoring across 45,000+ scored companies. Every score is reproducible — backed by stored facts, not black-box heuristics. Complete evidence chains."
              stats={[
                { label: "Companies scored", value: "45k+" },
                { label: "Evidence", value: "Full chain" },
                { label: "Versioned", value: "Always" },
              ]}
            />
          </div>
        </div>
      </section>

      {/* Five Layers */}
      <section
        style={{
          background: "#040a18",
          borderTop: "1px solid #1a2540",
        }}
      >
        <div className="max-w-6xl mx-auto px-6 py-24">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold text-white mb-3">
              Five layers of analysis
            </h2>
            <p className="text-gray-500 text-base">
              Macro to micro. Quantitative and fundamental. All scored and ranked.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <LayerCard
              step="01"
              title="Countries"
              description="GDP, inflation, stability, market performance — 10 investable economies scored."
            />
            <LayerCard
              step="02"
              title="Industries"
              description="Every GICS sector evaluated against live macro conditions in each country."
            />
            <LayerCard
              step="03"
              title="Companies"
              description="Fundamental ratios, market signals, and composite scores across hundreds of stocks."
            />
            <LayerCard
              step="04"
              title="ML Signals"
              description="770,000+ observations powering a 186-feature model that identifies outperformance patterns."
            />
            <LayerCard
              step="05"
              title="Portfolio"
              description="Kelly-sized positions with walk-forward backtesting and calibration."
            />
          </div>
        </div>
      </section>

      {/* How it works */}
      <section
        style={{
          background: "#060e1e",
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
              <h3 className="text-white font-semibold mb-2">Train a model</h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Configure parameters or use the validated golden defaults.
                Walk-forward CV trains and backtests automatically.
              </p>
            </div>

            <div>
              <div className="text-3xl font-bold text-brand mb-4 font-mono">
                03
              </div>
              <h3 className="text-white font-semibold mb-2">Get predictions</h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Calibrated probabilities, Kelly-sized portfolios, and
                deterministic scores — all with full transparency.
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
              Ready to find your edge?
            </h2>
            <p className="text-gray-500 mb-10 text-base">
              AI predictions. Deterministic scores. Full evidence lineage.
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

/* ── Helper components ──────────────────────────────────────────────── */

function FeatureCard({
  icon,
  title,
  description,
  stats,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  stats: { label: string; value: string }[];
}) {
  return (
    <div
      className="rounded-2xl border p-7 transition-all duration-200 hover:-translate-y-0.5"
      style={{ background: "#0a1525", borderColor: "#1e2d45" }}
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
      <div className="mb-5">{icon}</div>
      <h3 className="text-white font-semibold text-lg mb-3">{title}</h3>
      <p className="text-gray-500 text-sm leading-relaxed mb-5">{description}</p>
      <div className="flex gap-6">
        {stats.map((s) => (
          <div key={s.label}>
            <div className="text-white font-mono font-bold text-sm">{s.value}</div>
            <div className="text-gray-600 text-xs">{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LayerCard({
  step,
  title,
  description,
}: {
  step: string;
  title: string;
  description: string;
}) {
  return (
    <div
      className="rounded-xl border p-5 transition-all duration-200"
      style={{ background: "#0a1525", borderColor: "#1e2d45" }}
    >
      <div className="text-brand font-mono font-bold text-xs mb-2">{step}</div>
      <h3 className="text-white font-semibold text-sm mb-2">{title}</h3>
      <p className="text-gray-500 text-xs leading-relaxed">{description}</p>
    </div>
  );
}
