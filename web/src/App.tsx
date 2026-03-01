import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import NavBar from "@/components/NavBar";

const Home = lazy(() => import("@/pages/Home"));
const Login = lazy(() => import("@/pages/Login"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Countries = lazy(() => import("@/pages/Countries"));
const CountryDetail = lazy(() => import("@/pages/CountryDetail"));
const Industries = lazy(() => import("@/pages/Industries"));
const IndustryDetail = lazy(() => import("@/pages/IndustryDetail"));
const Jobs = lazy(() => import("@/pages/Jobs"));
const JobDetail = lazy(() => import("@/pages/JobDetail"));

export default function App() {
  return (
    <>
      <NavBar />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Suspense fallback={<div className="text-gray-500">Loading...</div>}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/countries" element={<Countries />} />
            <Route path="/countries/:iso2" element={<CountryDetail />} />
            <Route path="/industries" element={<Industries />} />
            <Route path="/industries/:gics_code" element={<IndustryDetail />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
          </Routes>
        </Suspense>
      </main>
    </>
  );
}
