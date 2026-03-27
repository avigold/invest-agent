import { useState, useRef, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useUser } from "@/lib/auth";

interface NavItem {
  to: string;
  label: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Research",
    items: [
      { to: "/watchlist", label: "Watchlist" },
      { to: "/countries", label: "Countries" },
      { to: "/industries", label: "Industries" },
      { to: "/companies", label: "Companies" },
    ],
  },
  {
    label: "Signals",
    items: [
      { to: "/ml/picks", label: "ML Picks" },
      { to: "/ml/models", label: "Models" },
      { to: "/fundamentals", label: "Fundamentals" },
      { to: "/screener", label: "Screener" },
      { to: "/compare", label: "Compare" },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/jobs", label: "Jobs" },
    ],
  },
];

function isGroupActive(group: NavGroup, pathname: string): boolean {
  return group.items.some(
    (item) => pathname === item.to || pathname.startsWith(item.to + "/"),
  );
}

function DesktopDropdown({ group }: { group: NavGroup }) {
  const [open, setOpen] = useState(false);
  const timeout = useRef<ReturnType<typeof setTimeout>>();
  const location = useLocation();
  const active = isGroupActive(group, location.pathname);

  const enter = () => {
    clearTimeout(timeout.current);
    setOpen(true);
  };
  const leave = () => {
    timeout.current = setTimeout(() => setOpen(false), 150);
  };

  useEffect(() => () => clearTimeout(timeout.current), []);

  return (
    <div className="relative" onMouseEnter={enter} onMouseLeave={leave}>
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1 text-sm ${
          active ? "text-white" : "text-gray-400 hover:text-white"
        }`}
      >
        {group.label}
        <svg
          className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 12 12"
        >
          <path d="M3 5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-2 min-w-[10rem] rounded-lg border border-gray-700 bg-gray-900 py-1 shadow-xl">
          {group.items.map((item) => {
            const itemActive =
              location.pathname === item.to ||
              location.pathname.startsWith(item.to + "/");
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={() => setOpen(false)}
                className={`block px-4 py-2 text-sm ${
                  itemActive
                    ? "bg-gray-800 text-white"
                    : "text-gray-300 hover:bg-gray-800 hover:text-white"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MobileGroup({
  group,
  onNavigate,
}: {
  group: NavGroup;
  onNavigate: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const location = useLocation();
  const active = isGroupActive(group, location.pathname);

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm ${
          active ? "text-white" : "text-gray-300"
        } hover:bg-gray-800`}
      >
        {group.label}
        <svg
          className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 12 12"
        >
          <path d="M3 5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
      {expanded && (
        <div className="ml-3 mt-1 flex flex-col gap-0.5">
          {group.items.map((item) => {
            const itemActive =
              location.pathname === item.to ||
              location.pathname.startsWith(item.to + "/");
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={onNavigate}
                className={`rounded-lg px-3 py-1.5 text-sm ${
                  itemActive
                    ? "bg-gray-800 text-white"
                    : "text-gray-400 hover:bg-gray-800 hover:text-white"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function NavBar() {
  const { user, loading, logout } = useUser();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <nav className="border-b border-gray-800 bg-gray-900">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        {/* Logo */}
        <Link to="/dashboard" className="flex items-center gap-2 shrink-0 group">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <polyline
              points="2,15 8,7 11,12 15.5,6"
              stroke="#6b7280"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="group-hover:stroke-gray-300 transition-colors"
            />
            <polygon
              points="18,2 17,8.5 12.5,5"
              fill="#6b7280"
              className="group-hover:fill-gray-300 transition-colors"
            />
          </svg>
          <span className="text-lg font-bold text-gray-300 tracking-tight group-hover:text-white transition-colors">
            Invest Agent
          </span>
        </Link>

        {/* Desktop nav */}
        {user && (
          <div className="hidden lg:flex items-center gap-6">
            {NAV_GROUPS.map((g) => (
              <DesktopDropdown key={g.label} group={g} />
            ))}
            {user.role === "admin" && (
              <Link to="/admin" className="text-sm text-purple-400 hover:text-purple-300">
                Admin
              </Link>
            )}
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
          onClick={() => setMobileOpen(!mobileOpen)}
          className="lg:hidden flex flex-col items-center justify-center w-8 h-8 gap-1.5"
          aria-label="Toggle menu"
        >
          <span
            className={`block h-0.5 w-5 bg-gray-400 transition-transform ${mobileOpen ? "translate-y-2 rotate-45" : ""}`}
          />
          <span
            className={`block h-0.5 w-5 bg-gray-400 transition-opacity ${mobileOpen ? "opacity-0" : ""}`}
          />
          <span
            className={`block h-0.5 w-5 bg-gray-400 transition-transform ${mobileOpen ? "-translate-y-2 -rotate-45" : ""}`}
          />
        </button>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="lg:hidden border-t border-gray-800 px-4 pb-4 pt-2">
          {user && (
            <div className="flex flex-col gap-1">
              {NAV_GROUPS.map((g) => (
                <MobileGroup
                  key={g.label}
                  group={g}
                  onNavigate={() => setMobileOpen(false)}
                />
              ))}
              {user.role === "admin" && (
                <Link
                  to="/admin"
                  onClick={() => setMobileOpen(false)}
                  className="rounded-lg px-3 py-2 text-sm text-purple-400 hover:bg-gray-800 hover:text-purple-300"
                >
                  Admin
                </Link>
              )}
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
                    setMobileOpen(false);
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
                onClick={() => setMobileOpen(false)}
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
