import { useEffect, useRef, useState } from "react";
import { apiJson, apiFetch } from "@/lib/api";
import WeightSlider from "./WeightSlider";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProfileSummary {
  id: string;
  name: string;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

interface ProfileConfig {
  recommendation_weights: { country: number; industry: number; company: number };
  thresholds: { buy: number; sell: number };
  country_weights: { macro: number; market: number; stability: number };
  country_macro_indicator_weights: Record<string, number>;
  country_market_metric_weights: Record<string, number>;
  company_weights: { fundamental: number; market: number };
  company_fundamental_ratio_weights: Record<string, number>;
  company_market_metric_weights: Record<string, number>;
}

interface ProfileFull extends ProfileSummary {
  config: ProfileConfig;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onProfileChange: (profileId: string | null) => void;
  activeProfileId: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const INDICATOR_LABELS: Record<string, string> = {
  gdp_growth: "GDP Growth",
  inflation: "Inflation",
  unemployment: "Unemployment",
  govt_debt_gdp: "Govt Debt / GDP",
  current_account_gdp: "Current Account / GDP",
  fdi_gdp: "FDI / GDP",
  reserves: "Reserves",
  gdp_per_capita: "GDP per Capita",
  market_cap_gdp: "Market Cap / GDP",
  household_consumption_pc: "Household Consumption",
  return_1y: "1Y Return",
  max_drawdown: "Max Drawdown",
  ma_spread: "MA Spread",
  roe: "ROE",
  net_margin: "Net Margin",
  debt_equity: "Debt / Equity",
  revenue_growth: "Revenue Growth",
  eps_growth: "EPS Growth",
  fcf_yield: "FCF Yield",
};

function normalizeGroup(
  weights: Record<string, number>,
  changedKey: string,
  newValue: number,
): Record<string, number> {
  const keys = Object.keys(weights);
  const others = keys.filter((k) => k !== changedKey);
  const remaining = 1 - newValue;

  if (remaining <= 0) {
    const result: Record<string, number> = {};
    for (const k of keys) result[k] = k === changedKey ? 1 : 0;
    return result;
  }

  const otherSum = others.reduce((s, k) => s + weights[k], 0);
  const result: Record<string, number> = { [changedKey]: newValue };

  if (otherSum === 0) {
    const share = remaining / others.length;
    for (const k of others) result[k] = share;
  } else {
    for (const k of others) {
      result[k] = (weights[k] / otherSum) * remaining;
    }
  }
  return result;
}

function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj));
}

function configsEqual(a: ProfileConfig, b: ProfileConfig): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ScoringProfileModal({
  open,
  onClose,
  onProfileChange,
  activeProfileId,
}: Props) {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [defaults, setDefaults] = useState<ProfileConfig | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [config, setConfig] = useState<ProfileConfig | null>(null);
  const [profileName, setProfileName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());

  // Snapshot of the config when a profile was loaded, to detect changes
  const savedConfigRef = useRef<ProfileConfig | null>(null);
  const savedNameRef = useRef<string>("");

  // Load profiles and defaults on open
  useEffect(() => {
    if (!open) return;
    setError("");
    Promise.all([
      apiJson<ProfileSummary[]>("/v1/scoring-profiles"),
      apiJson<ProfileConfig>("/v1/scoring-profiles/defaults"),
    ]).then(([profs, defs]) => {
      setProfiles(profs);
      setDefaults(defs);
      if (activeProfileId) {
        loadProfile(activeProfileId);
      } else {
        setSelectedId(null);
        setConfig(deepClone(defs));
        setProfileName("");
        savedConfigRef.current = deepClone(defs);
        savedNameRef.current = "";
      }
    });
  }, [open]);

  const loadProfile = async (id: string) => {
    const p = await apiJson<ProfileFull>(`/v1/scoring-profiles/${id}`);
    setSelectedId(p.id);
    setConfig(deepClone(p.config));
    setProfileName(p.name);
    savedConfigRef.current = deepClone(p.config);
    savedNameRef.current = p.name;
  };

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (!open || !config || !defaults) return null;

  const hasChanges =
    !savedConfigRef.current ||
    !configsEqual(config, savedConfigRef.current) ||
    profileName !== savedNameRef.current;

  // Update helpers
  const updateRecWeights = (key: string, val: number) => {
    setConfig((c) => {
      if (!c) return c;
      return { ...c, recommendation_weights: normalizeGroup(c.recommendation_weights, key, val) as typeof c.recommendation_weights };
    });
  };

  const updateCountryWeights = (key: string, val: number) => {
    setConfig((c) => {
      if (!c) return c;
      return { ...c, country_weights: normalizeGroup(c.country_weights, key, val) as typeof c.country_weights };
    });
  };

  const updateCompanyWeights = (key: string, val: number) => {
    setConfig((c) => {
      if (!c) return c;
      return { ...c, company_weights: normalizeGroup(c.company_weights, key, val) as typeof c.company_weights };
    });
  };

  const updateIndicator = (field: keyof ProfileConfig, key: string, val: number) => {
    setConfig((c) => {
      if (!c) return c;
      return { ...c, [field]: { ...(c[field] as Record<string, number>), [key]: val } };
    });
  };

  const updateThreshold = (key: "buy" | "sell", val: number) => {
    setConfig((c) => {
      if (!c) return c;
      return { ...c, thresholds: { ...c.thresholds, [key]: val } };
    });
  };

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    setError("");
    try {
      if (selectedId) {
        // Existing profile: update if changed, then activate
        if (hasChanges) {
          await apiJson(`/v1/scoring-profiles/${selectedId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: profileName, config }),
          });
        }
        await apiJson(`/v1/scoring-profiles/${selectedId}/activate`, { method: "POST" });
        onProfileChange(selectedId);
      } else {
        // No profile selected — creating new
        const name = profileName.trim() || "My Profile";

        // Check if a profile with this name already exists, and update it instead
        const existing = profiles.find(
          (p) => p.name.toLowerCase() === name.toLowerCase(),
        );
        if (existing) {
          await apiJson(`/v1/scoring-profiles/${existing.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, config }),
          });
          await apiJson(`/v1/scoring-profiles/${existing.id}/activate`, { method: "POST" });
          onProfileChange(existing.id);
        } else {
          const created = await apiJson<ProfileFull>("/v1/scoring-profiles", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, config }),
          });
          await apiJson(`/v1/scoring-profiles/${created.id}/activate`, { method: "POST" });
          onProfileChange(created.id);
        }
      }
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAsNew = async () => {
    if (!config) return;
    setSaving(true);
    setError("");
    try {
      const base = profileName.trim() || "My Profile";
      // Find a unique name by appending (copy), (copy 2), etc.
      let name = `${base} (copy)`;
      const existingNames = new Set(profiles.map((p) => p.name.toLowerCase()));
      let attempt = 1;
      while (existingNames.has(name.toLowerCase())) {
        attempt++;
        name = `${base} (copy ${attempt})`;
      }

      const created = await apiJson<ProfileFull>("/v1/scoring-profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, config }),
      });
      await apiJson(`/v1/scoring-profiles/${created.id}/activate`, { method: "POST" });
      onProfileChange(created.id);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId) return;
    setSaving(true);
    try {
      await apiFetch(`/v1/scoring-profiles/${selectedId}`, { method: "DELETE" });
      onProfileChange(null);
      onClose();
    } catch {
      setError("Delete failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDeactivate = async () => {
    try {
      await apiJson("/v1/scoring-profiles/deactivate", { method: "POST" });
      onProfileChange(null);
      onClose();
    } catch {
      setError("Failed to deactivate");
    }
  };

  const handleReset = () => {
    if (defaults) {
      setConfig(deepClone(defaults));
    }
  };

  const sectionToggle = (key: string, label: string) => (
    <button
      onClick={() => toggleSection(key)}
      className="flex w-full items-center justify-between py-2 text-sm font-medium text-gray-300 hover:text-white transition-colors"
    >
      {label}
      <span className="text-gray-600 text-xs">
        {expandedSections.has(key) ? "▼" : "▶"}
      </span>
    </button>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-lg border border-gray-700 bg-gray-900 p-6 shadow-2xl">
        <h2 className="text-lg font-bold text-white mb-4">Scoring Profile</h2>

        {/* Profile selector */}
        <div className="mb-4 flex items-center gap-2">
          <select
            value={selectedId || "__defaults__"}
            onChange={(e) => {
              const val = e.target.value;
              if (val === "__defaults__") {
                setSelectedId(null);
                setConfig(deepClone(defaults));
                setProfileName("");
                savedConfigRef.current = deepClone(defaults);
                savedNameRef.current = "";
              } else {
                loadProfile(val);
              }
              setError("");
            }}
            className="flex-1 rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300"
          >
            <option value="__defaults__">System Defaults</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {/* Profile name */}
        <div className="mb-5">
          <input
            type="text"
            value={profileName}
            onChange={(e) => setProfileName(e.target.value)}
            placeholder="Profile name..."
            className="w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 placeholder-gray-600"
          />
        </div>

        {/* Recommendation weights */}
        <div className="mb-5 rounded border border-gray-800 p-4">
          <h3 className="mb-3 text-sm font-semibold text-white uppercase tracking-wider">
            Recommendation Weights
          </h3>
          <div className="space-y-2">
            <WeightSlider label="Country" value={config.recommendation_weights.country} onChange={(v) => updateRecWeights("country", v)} />
            <WeightSlider label="Industry" value={config.recommendation_weights.industry} onChange={(v) => updateRecWeights("industry", v)} />
            <WeightSlider label="Company" value={config.recommendation_weights.company} onChange={(v) => updateRecWeights("company", v)} />
          </div>
        </div>

        {/* Thresholds */}
        <div className="mb-5 rounded border border-gray-800 p-4">
          <h3 className="mb-3 text-sm font-semibold text-white uppercase tracking-wider">
            Classification Thresholds
          </h3>
          <div className="space-y-2">
            <WeightSlider label="Buy >" value={config.thresholds.buy} min={0} max={100} step={1} onChange={(v) => updateThreshold("buy", v)} displayFormat={(v) => v.toFixed(0)} />
            <WeightSlider label="Sell <" value={config.thresholds.sell} min={0} max={100} step={1} onChange={(v) => updateThreshold("sell", v)} displayFormat={(v) => v.toFixed(0)} />
          </div>
        </div>

        {/* Country scoring */}
        <div className="mb-5 rounded border border-gray-800 p-4">
          <h3 className="mb-3 text-sm font-semibold text-white uppercase tracking-wider">
            Country Scoring
          </h3>
          <div className="space-y-2 mb-3">
            <WeightSlider label="Macro" value={config.country_weights.macro} onChange={(v) => updateCountryWeights("macro", v)} />
            <WeightSlider label="Market" value={config.country_weights.market} onChange={(v) => updateCountryWeights("market", v)} />
            <WeightSlider label="Stability" value={config.country_weights.stability} onChange={(v) => updateCountryWeights("stability", v)} />
          </div>

          {/* Macro indicators */}
          <div className="border-t border-gray-800 pt-2">
            {sectionToggle("macro_ind", "Macro Indicator Weights")}
            {expandedSections.has("macro_ind") && (
              <div className="space-y-1.5 pl-2 pt-1">
                {Object.keys(config.country_macro_indicator_weights).map((key) => (
                  <WeightSlider
                    key={key}
                    label={INDICATOR_LABELS[key] || key}
                    value={config.country_macro_indicator_weights[key]}
                    min={0}
                    max={5}
                    step={0.1}
                    onChange={(v) => updateIndicator("country_macro_indicator_weights", key, v)}
                    displayFormat={(v) => v.toFixed(1)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Market metrics */}
          <div className="border-t border-gray-800 pt-2">
            {sectionToggle("country_mkt", "Market Metric Weights")}
            {expandedSections.has("country_mkt") && (
              <div className="space-y-1.5 pl-2 pt-1">
                {Object.keys(config.country_market_metric_weights).map((key) => (
                  <WeightSlider
                    key={key}
                    label={INDICATOR_LABELS[key] || key}
                    value={config.country_market_metric_weights[key]}
                    min={0}
                    max={5}
                    step={0.1}
                    onChange={(v) => updateIndicator("country_market_metric_weights", key, v)}
                    displayFormat={(v) => v.toFixed(1)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Company scoring */}
        <div className="mb-5 rounded border border-gray-800 p-4">
          <h3 className="mb-3 text-sm font-semibold text-white uppercase tracking-wider">
            Company Scoring
          </h3>
          <div className="space-y-2 mb-3">
            <WeightSlider label="Fundamental" value={config.company_weights.fundamental} onChange={(v) => updateCompanyWeights("fundamental", v)} />
            <WeightSlider label="Market" value={config.company_weights.market} onChange={(v) => updateCompanyWeights("market", v)} />
          </div>

          {/* Fundamental ratios */}
          <div className="border-t border-gray-800 pt-2">
            {sectionToggle("fund_ratios", "Fundamental Ratio Weights")}
            {expandedSections.has("fund_ratios") && (
              <div className="space-y-1.5 pl-2 pt-1">
                {Object.keys(config.company_fundamental_ratio_weights).map((key) => (
                  <WeightSlider
                    key={key}
                    label={INDICATOR_LABELS[key] || key}
                    value={config.company_fundamental_ratio_weights[key]}
                    min={0}
                    max={5}
                    step={0.1}
                    onChange={(v) => updateIndicator("company_fundamental_ratio_weights", key, v)}
                    displayFormat={(v) => v.toFixed(1)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Market metrics */}
          <div className="border-t border-gray-800 pt-2">
            {sectionToggle("company_mkt", "Market Metric Weights")}
            {expandedSections.has("company_mkt") && (
              <div className="space-y-1.5 pl-2 pt-1">
                {Object.keys(config.company_market_metric_weights).map((key) => (
                  <WeightSlider
                    key={key}
                    label={INDICATOR_LABELS[key] || key}
                    value={config.company_market_metric_weights[key]}
                    min={0}
                    max={5}
                    step={0.1}
                    onChange={(v) => updateIndicator("company_market_metric_weights", key, v)}
                    displayFormat={(v) => v.toFixed(1)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Industry note */}
        <p className="mb-5 text-xs text-gray-600">
          Industry scoring uses a rubric and is not decomposable. Adjust its influence via the recommendation-level weight above.
        </p>

        {/* Error */}
        {error && (
          <div className="mb-4 rounded border border-red-800 bg-red-950/30 p-2 text-sm text-red-400">
            {error}
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleSave}
            disabled={saving || (selectedId != null && !hasChanges)}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {selectedId ? "Save & Apply" : "Create & Apply"}
          </button>
          {selectedId && (
            <button
              onClick={handleSaveAsNew}
              disabled={saving}
              className="rounded border border-gray-600 px-4 py-2 text-sm text-gray-300 hover:bg-gray-800 disabled:opacity-50"
            >
              Save As New
            </button>
          )}
          <button
            onClick={handleReset}
            className="rounded border border-gray-700 px-4 py-2 text-sm text-gray-400 hover:bg-gray-800"
          >
            Reset to Defaults
          </button>
          {activeProfileId && (
            <button
              onClick={handleDeactivate}
              className="rounded border border-yellow-800/50 px-4 py-2 text-sm text-yellow-500 hover:bg-yellow-950/20"
            >
              Use System Defaults
            </button>
          )}
          {selectedId && (
            <button
              onClick={handleDelete}
              disabled={saving}
              className="rounded border border-red-800/50 px-4 py-2 text-sm text-red-500 hover:bg-red-950/20 disabled:opacity-50"
            >
              Delete
            </button>
          )}
          <button
            onClick={onClose}
            className="ml-auto rounded border border-gray-700 px-4 py-2 text-sm text-gray-400 hover:bg-gray-800"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
