import { useState } from "react";
import { Link } from "react-router-dom";
import { useUser } from "@/lib/auth";

const NAV_LINKS = [
  { to: "/countries", label: "Countries" },
  { to: "/industries", label: "Industries" },
  { to: "/companies", label: "Companies" },
  { to: "/recommendations", label: "Recommendations" },
  { to: "/jobs", label: "Jobs" },
];

export default function NavBar() {
  const { user, loading, logout } = useUser();
  const [open, setOpen] = useState(false);

  return (
    <nav className="border-b border-gray-800 bg-gray-900">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        {/* Logo */}
        <Link to="/dashboard" className="flex items-center gap-2 shrink-0 group">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <polyline
              points="2,15 8,7 11,12 18,3"
              stroke="#6b7280"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="group-hover:stroke-gray-300 transition-colors"
            />
          </svg>
          <span className="text-lg font-bold text-gray-300 tracking-tight group-hover:text-white transition-colors">
            Invest Agent
          </span>
        </Link>

        {/* Desktop nav */}
        {user && (
          <div className="hidden lg:flex items-center gap-6">
            {NAV_LINKS.map((l) => (
              <Link
                key={l.to}
                to={l.to}
                className="text-sm text-gray-400 hover:text-white"
              >
                {l.label}
              </Link>
            ))}
          </div>
        )}

        {/* Desktop account */}
        <div className="hidden lg:flex items-center gap-4">
          {loading ? null : user ? (
            <>
              <span className="text-sm text-gray-400">{user.name}</span>
              <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-300 uppercase">
                {user.plan}
              </span>
              <button
                onClick={logout}
                className="text-sm text-gray-400 hover:text-white"
              >
                Log out
              </button>
            </>
          ) : (
            <Link
              to="/login"
              className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-dark"
            >
              Sign in
            </Link>
          )}
        </div>

        {/* Mobile hamburger */}
        <button
          onClick={() => setOpen(!open)}
          className="lg:hidden flex flex-col items-center justify-center w-8 h-8 gap-1.5"
          aria-label="Toggle menu"
        >
          <span
            className={`block h-0.5 w-5 bg-gray-400 transition-transform ${open ? "translate-y-2 rotate-45" : ""}`}
          />
          <span
            className={`block h-0.5 w-5 bg-gray-400 transition-opacity ${open ? "opacity-0" : ""}`}
          />
          <span
            className={`block h-0.5 w-5 bg-gray-400 transition-transform ${open ? "-translate-y-2 -rotate-45" : ""}`}
          />
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="lg:hidden border-t border-gray-800 px-4 pb-4 pt-2">
          {user && (
            <div className="flex flex-col gap-1">
              {NAV_LINKS.map((l) => (
                <Link
                  key={l.to}
                  to={l.to}
                  onClick={() => setOpen(false)}
                  className="rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-white"
                >
                  {l.label}
                </Link>
              ))}
            </div>
          )}
          <div className="mt-3 border-t border-gray-800 pt-3">
            {loading ? null : user ? (
              <div className="flex items-center justify-between px-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-400">{user.name}</span>
                  <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-300 uppercase">
                    {user.plan}
                  </span>
                </div>
                <button
                  onClick={() => {
                    setOpen(false);
                    logout();
                  }}
                  className="text-sm text-gray-400 hover:text-white"
                >
                  Log out
                </button>
              </div>
            ) : (
              <Link
                to="/login"
                onClick={() => setOpen(false)}
                className="block rounded bg-brand px-3 py-1.5 text-center text-sm font-medium text-white hover:bg-brand-dark"
              >
                Sign in
              </Link>
            )}
          </div>
        </div>
      )}
    </nav>
  );
}
