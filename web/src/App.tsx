import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import NavBar from "@/components/NavBar";

const Home = lazy(() => import("@/pages/Home"));
const Login = lazy(() => import("@/pages/Login"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Countries = lazy(() => import("@/pages/Countries"));
const CountryDetail = lazy(() => import("@/pages/CountryDetail"));
const Companies = lazy(() => import("@/pages/Companies"));
const AddCompanies = lazy(() => import("@/pages/AddCompanies"));
const CompanyDetail = lazy(() => import("@/pages/CompanyDetail"));
const Industries = lazy(() => import("@/pages/Industries"));
const IndustryDetail = lazy(() => import("@/pages/IndustryDetail"));
const Recommendations = lazy(() => import("@/pages/Recommendations"));
const RecommendationDetail = lazy(() => import("@/pages/RecommendationDetail"));
const Jobs = lazy(() => import("@/pages/Jobs"));
const JobDetail = lazy(() => import("@/pages/JobDetail"));
const Admin = lazy(() => import("@/pages/Admin"));
const Screener = lazy(() => import("@/pages/Screener"));
const ScreenerResult = lazy(() => import("@/pages/ScreenerResult"));
const Predictions = lazy(() => import("@/pages/Predictions"));
const PredictionDetail = lazy(() => import("@/pages/PredictionDetail"));

export default function App() {
  return (
    <>
      <NavBar />
      <Suspense fallback={<div className="mx-auto max-w-6xl px-4 py-8 text-gray-500">Loading...</div>}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route
            path="*"
            element={
              <main className="mx-auto max-w-6xl px-4 py-8">
                <Routes>
                  <Route path="/login" element={<Login />} />
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/countries" element={<Countries />} />
                  <Route path="/countries/:iso2" element={<CountryDetail />} />
                  <Route path="/recommendations" element={<Recommendations />} />
                  <Route path="/recommendations/:ticker" element={<RecommendationDetail />} />
                  <Route path="/companies" element={<Companies />} />
                  <Route path="/companies/add" element={<AddCompanies />} />
                  <Route path="/companies/:ticker" element={<CompanyDetail />} />
                  <Route path="/industries" element={<Industries />} />
                  <Route path="/industries/:gics_code" element={<IndustryDetail />} />
                  <Route path="/jobs" element={<Jobs />} />
                  <Route path="/jobs/:id" element={<JobDetail />} />
                  <Route path="/screener" element={<Screener />} />
                  <Route path="/screener/:id" element={<ScreenerResult />} />
                  <Route path="/predictions" element={<Predictions />} />
                  <Route path="/predictions/:id" element={<PredictionDetail />} />
                  <Route path="/admin" element={<Admin />} />
                </Routes>
              </main>
            }
          />
        </Routes>
      </Suspense>
    </>
  );
}
