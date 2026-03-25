import { useState, useCallback, useEffect, useRef } from "react";
import FilterBuilder from "./FilterBuilder";
import ScreenerResults, { type ScreenerRow } from "./ScreenerResults";
import SavedScreens, { type SavedScreen } from "./SavedScreens";
import type { Rule, FieldDef } from "./FilterRule";
import {
  useScreenFields,
  useSavedScreens,
  useSaveScreen,
  useUpdateSavedScreen,
  useDeleteSavedScreen,
} from "@/lib/queries";
import { apiJson } from "@/lib/api";
import { exportToCsv, todayStr } from "@/lib/export";

interface ScreenResponse {
  total: number;
  items: ScreenerRow[];
}

export default function LiveScreener() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [sortBy, setSortBy] = useState("probability");
  const [sortDesc, setSortDesc] = useState(true);

  // Active screen tracking
  const [activeScreenId, setActiveScreenId] = useState<string | null>(null);
  const [activeScreenName, setActiveScreenName] = useState<string | null>(null);

  // Screen results (managed manually, not via useQuery, because POST)
  const [rows, setRows] = useState<ScreenerRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch refs for debouncing
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const abortRef = useRef<AbortController>();

  // Data hooks
  const { data: fieldsData } = useScreenFields();
  const fields: FieldDef[] = (fieldsData as { fields: FieldDef[] } | undefined)?.fields ?? [];

  const { data: savedData } = useSavedScreens();
  const savedScreens: SavedScreen[] =
    (savedData as { items: SavedScreen[] } | undefined)?.items ?? [];

  const saveScreen = useSaveScreen();
  const updateScreen = useUpdateSavedScreen();
  const deleteScreen = useDeleteSavedScreen();

  // Fetch screen results
  const fetchResults = useCallback(
    async (filterRules: Rule[], sort: string, desc: boolean) => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;

      setLoading(true);
      setError(null);
      try {
        // Only send rules with valid field + value
        const valid = filterRules.filter((r) => {
          if (!r.field) return false;
          if (Array.isArray(r.value)) return r.value.length > 0;
          return r.value !== "" && r.value != null;
        });

        const data = await apiJson<ScreenResponse>("/v1/screener/live/screen", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filters: { rules: valid },
            sort_by: sort,
            sort_desc: desc,
            limit: 200,
            offset: 0,
          }),
          signal: ac.signal,
        });
        if (!ac.signal.aborted) {
          setRows(data.items ?? []);
          setTotal(data.total ?? 0);
        }
      } catch (e: unknown) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (!ac.signal.aborted) {
          setError(e instanceof Error ? e.message : "Failed to screen");
          setRows([]);
          setTotal(0);
        }
      } finally {
        if (!ac.signal.aborted) setLoading(false);
      }
    },
    [],
  );

  // Debounced fetch on any filter/sort change (including initial mount)
  useEffect(() => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      fetchResults(rules, sortBy, sortDesc);
    }, 100);
    return () => clearTimeout(timerRef.current);
  }, [rules, sortBy, sortDesc, fetchResults]);

  const handleSort = useCallback(
    (field: string) => {
      if (sortBy === field) {
        setSortDesc((d) => !d);
      } else {
        setSortBy(field);
        setSortDesc(true);
      }
    },
    [sortBy],
  );

  const handleLoad = useCallback((screen: SavedScreen) => {
    setRules(screen.filters?.rules ?? []);
    if (screen.sort_by) setSortBy(screen.sort_by);
    if (screen.sort_desc != null) setSortDesc(screen.sort_desc);
    setActiveScreenId(screen.id);
    setActiveScreenName(screen.name);
  }, []);

  const handleSave = useCallback(
    (name: string) => {
      saveScreen.mutate(
        { name, filters: { rules }, sort_by: sortBy, sort_desc: sortDesc },
        {
          onSuccess: (data: unknown) => {
            const saved = data as { id: string; name: string };
            setActiveScreenId(saved.id);
            setActiveScreenName(saved.name);
          },
        },
      );
    },
    [rules, sortBy, sortDesc, saveScreen],
  );

  const handleUpdate = useCallback(() => {
    if (!activeScreenId || activeScreenId.startsWith("tpl_")) return;
    updateScreen.mutate({
      id: activeScreenId,
      name: activeScreenName ?? "Untitled",
      filters: { rules },
      sort_by: sortBy,
      sort_desc: sortDesc,
    });
  }, [activeScreenId, activeScreenName, rules, sortBy, sortDesc, updateScreen]);

  const handleDelete = useCallback(
    (id: string) => {
      deleteScreen.mutate(id, {
        onSuccess: () => {
          if (activeScreenId === id) {
            setActiveScreenId(null);
            setActiveScreenName(null);
          }
        },
      });
    },
    [activeScreenId, deleteScreen],
  );

  const handleClear = useCallback(() => {
    setRules([]);
    setActiveScreenId(null);
    setActiveScreenName(null);
  }, []);

  const handleExport = useCallback(() => {
    if (!rows.length) return;
    const fmtPct = (v: number | null | undefined) => (v != null ? (v * 100).toFixed(1) + "%" : "");
    exportToCsv(
      `screener_${todayStr()}.csv`,
      ["Ticker", "Name", "Country", "Sector", "P/E", "P/B", "ROE", "Net Margin", "Rev Growth", "ML Prob", "Classification"],
      rows.map((r) => [
        r.ticker, r.company_name, r.country, r.sector,
        r.pe_ratio != null ? r.pe_ratio.toFixed(1) : "",
        r.pb_ratio != null ? r.pb_ratio.toFixed(1) : "",
        fmtPct(r.roe), fmtPct(r.net_margin), fmtPct(r.revenue_growth),
        fmtPct(r.probability),
        r.det_classification ?? "",
      ]),
    );
  }, [rows]);

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <SavedScreens
        screens={savedScreens}
        activeId={activeScreenId}
        activeName={activeScreenName}
        onLoad={handleLoad}
        onSave={handleSave}
        onUpdate={handleUpdate}
        onDelete={handleDelete}
        hasFilters={rules.length > 0}
        hasRows={rows.length > 0}
        onClear={handleClear}
        onExport={handleExport}
      />

      {/* Filter builder */}
      <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
        <FilterBuilder rules={rules} fields={fields} onChange={setRules} />
      </div>

      {/* Error */}
      {error && (
        <div className="rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

{/* Results */}
      <ScreenerResults
        rows={rows}
        total={total}
        sortBy={sortBy}
        sortDesc={sortDesc}
        onSort={handleSort}
        loading={loading}
      />
    </div>
  );
}
