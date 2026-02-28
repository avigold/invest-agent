"use client";

import Link from "next/link";
import { useUser } from "@/lib/auth";

export default function NavBar() {
  const { user, loading, logout } = useUser();

  return (
    <nav className="border-b border-gray-800 bg-gray-900">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <Link href="/" className="text-lg font-bold text-white">
            Invest Agent
          </Link>
          {user && (
            <>
              <Link
                href="/dashboard"
                className="text-sm text-gray-400 hover:text-white"
              >
                Dashboard
              </Link>
              <Link
                href="/countries"
                className="text-sm text-gray-400 hover:text-white"
              >
                Countries
              </Link>
              <Link
                href="/jobs"
                className="text-sm text-gray-400 hover:text-white"
              >
                Jobs
              </Link>
            </>
          )}
        </div>
        <div className="flex items-center gap-4">
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
              href="/login"
              className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-dark"
            >
              Sign in
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}
