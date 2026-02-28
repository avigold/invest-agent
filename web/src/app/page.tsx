"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useUser } from "@/lib/auth";

export default function Home() {
  const { user, loading } = useUser();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) {
      router.replace("/dashboard");
    }
  }, [user, loading, router]);

  if (loading) return null;

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <h1 className="mb-4 text-4xl font-bold text-white">Invest Agent</h1>
      <p className="mb-8 max-w-lg text-lg text-gray-400">
        Automated investment research. Ingest macro, industry, and company data.
        Compute deterministic scores. Make better decisions.
      </p>
      <Link
        href="/login"
        className="rounded-lg bg-brand px-6 py-3 text-lg font-medium text-white hover:bg-brand-dark"
      >
        Get started
      </Link>
    </div>
  );
}
