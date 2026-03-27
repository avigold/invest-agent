import { useEffect, useRef, useState, useCallback } from "react";
import {
  createChart,
  LineSeries,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
} from "lightweight-charts";
import { useQueries } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { queryKeys } from "@/lib/queries";

// ── Types ────────────────────────────────────────────────────────────────

interface ChartPoint {
  date: string;
  value: number;
  volume?: number;
}

interface ChartResponse {
  ticker: string;
  points: ChartPoint[];
}

// ── Constants ────────────────────────────────────────────────────────────

const PERIODS = ["1M", "3M", "6M", "1Y", "5Y"] as const;

const COLORS = [
  "#3b82f6", // blue
  "#f59e0b", // amber
  "#10b981", // emerald
  "#8b5cf6", // violet
  "#ef4444", // red
];

const PCT_FORMAT = {
  type: "custom" as const,
  formatter: (price: number) => `${price >= 0 ? "+" : ""}${price.toFixed(1)}%`,
};

// ── Normalisation ────────────────────────────────────────────────────────

interface NormalisedSeries {
  ticker: string;
  color: string;
  points: { time: string; value: number }[];
}

function normalise(
  tickers: string[],
  responses: (ChartResponse | undefined)[],
): NormalisedSeries[] {
  // Collect all valid datasets
  const datasets: { ticker: string; color: string; pts: ChartPoint[] }[] = [];
  for (let i = 0; i < tickers.length; i++) {
    const resp = responses[i];
    if (!resp || resp.points.length === 0) continue;
    datasets.push({
      ticker: tickers[i],
      color: COLORS[i % COLORS.length],
      pts: resp.points,
    });
  }

  if (datasets.length === 0) return [];

  // Find latest common start date
  const startDates = datasets.map((d) => d.pts[0].date);
  const commonStart = startDates.sort().pop()!;

  return datasets.map((d) => {
    // Find first point on or after commonStart
    const startIdx = d.pts.findIndex((p) => p.date >= commonStart);
    if (startIdx < 0) return { ticker: d.ticker, color: d.color, points: [] };
    const base = d.pts[startIdx].value;
    if (base === 0) return { ticker: d.ticker, color: d.color, points: [] };

    const points = d.pts.slice(startIdx).map((p) => ({
      time: p.date,
      value: ((p.value - base) / base) * 100,
    }));
    return { ticker: d.ticker, color: d.color, points };
  });
}

// ── Component ────────────────────────────────────────────────────────────

export default function CompareChart({ tickers }: { tickers: string[] }) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesMapRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const [period, setPeriod] = useState("1y");
  const [legendValues, setLegendValues] = useState<
    Map<string, { value: number; color: string }>
  >(new Map());

  // Fetch chart data for all tickers in parallel
  const chartQueries = useQueries({
    queries: tickers.map((ticker) => ({
      queryKey: queryKeys.chart(ticker, period),
      queryFn: () =>
        apiJson<ChartResponse>(
          `/v1/company/${ticker.replace(/\./g, "-")}/chart?period=${period}`,
        ),
      enabled: !!ticker,
      staleTime: 60_000,
      retry: false as const,
    })),
  });

  const responses = chartQueries.map((q) => q.data);
  const anyLoading = chartQueries.some((q) => q.isLoading);
  const allSettled = chartQueries.every((q) => !q.isLoading);

  // Create chart once
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: "transparent" },
        textColor: "#9ca3af",
      },
      grid: {
        vertLines: { color: "#1f293780" },
        horzLines: { color: "#1f293780" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "#6b728080",
          width: 1,
          style: 3,
          labelBackgroundColor: "#374151",
        },
        horzLine: {
          color: "#6b728080",
          width: 1,
          style: 3,
          labelBackgroundColor: "#374151",
        },
      },
      rightPriceScale: {
        borderColor: "#374151",
        minimumWidth: 70,
        entireTextOnly: true,
      },
      timeScale: {
        borderColor: "#374151",
        timeVisible: false,
      },
      width: chartContainerRef.current.clientWidth,
      height: window.innerWidth >= 768 ? 350 : 250,
    });

    chartRef.current = chart;

    // Remove TradingView branding
    const brandingLink = chartContainerRef.current.querySelector(
      'a[href*="tradingview"]',
    );
    if (brandingLink) brandingLink.remove();

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesMapRef.current.clear();
    };
  }, []);

  // Resize observer
  useEffect(() => {
    if (!chartContainerRef.current || !chartRef.current) return;
    const container = chartContainerRef.current;
    const chart = chartRef.current;

    const observer = new ResizeObserver((entries) => {
      const { width } = entries[0].contentRect;
      chart.applyOptions({ width });
    });
    observer.observe(container);

    const handleResize = () => {
      chart.applyOptions({
        height: window.innerWidth >= 768 ? 350 : 250,
      });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  // Sync data to chart series
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const normalised = normalise(tickers, responses);
    const existingSeries = seriesMapRef.current;
    const activeTickers = new Set(normalised.map((n) => n.ticker));

    // Remove series for tickers no longer present
    for (const [ticker, series] of existingSeries) {
      if (!activeTickers.has(ticker)) {
        chart.removeSeries(series);
        existingSeries.delete(ticker);
      }
    }

    // Add or update series for each ticker
    for (const ns of normalised) {
      let series = existingSeries.get(ns.ticker);
      if (!series) {
        series = chart.addSeries(LineSeries, {
          color: ns.color,
          lineWidth: 2,
          crosshairMarkerVisible: true,
          crosshairMarkerRadius: 3,
          crosshairMarkerBorderColor: ns.color,
          crosshairMarkerBackgroundColor: ns.color + "40",
          priceFormat: PCT_FORMAT,
        });
        existingSeries.set(ns.ticker, series);
      }
      series.setData(ns.points);
    }

    chart.timeScale().fitContent();

    // Set up crosshair handler
    const handler = (param: MouseEventParams) => {
      if (!param.time || !param.point) {
        setLegendValues(new Map());
        return;
      }
      const vals = new Map<string, { value: number; color: string }>();
      for (const ns of normalised) {
        const series = existingSeries.get(ns.ticker);
        if (!series) continue;
        const d = param.seriesData.get(series);
        if (d && "value" in d) {
          vals.set(ns.ticker, {
            value: (d as { value: number }).value,
            color: ns.color,
          });
        }
      }
      setLegendValues(vals);
    };

    chart.subscribeCrosshairMove(handler);
    return () => {
      chart.unsubscribeCrosshairMove(handler);
    };
  }, [tickers, responses]);

  // Build static legend (last values) when not hovering
  const normalisedForLegend = normalise(tickers, responses);
  const staticLegend = normalisedForLegend.map((ns) => {
    const lastPt = ns.points.length > 0 ? ns.points[ns.points.length - 1] : null;
    return {
      ticker: ns.ticker,
      color: ns.color,
      value: lastPt?.value ?? null,
    };
  });

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-5 mb-6">
      {/* Legend */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 mb-3 min-h-[20px]">
        {staticLegend.map((item) => {
          const hover = legendValues.get(item.ticker);
          const val = hover?.value ?? item.value;
          return (
            <div key={item.ticker} className="flex items-center gap-1.5 text-xs">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: item.color }}
              />
              <span className="text-gray-400">{item.ticker}</span>
              {val != null && (
                <span
                  className={`font-mono font-medium ${val >= 0 ? "text-green-400" : "text-red-400"}`}
                >
                  {val >= 0 ? "+" : ""}
                  {val.toFixed(1)}%
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Period selector */}
      <div className="flex items-center gap-1 mb-3">
        {PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p.toLowerCase())}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              period === p.toLowerCase()
                ? "bg-blue-600 text-white"
                : "bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700"
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div className="relative">
        {anyLoading && !allSettled && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
              Loading charts...
            </div>
          </div>
        )}
        <div
          ref={chartContainerRef}
          className="w-full h-[250px] md:h-[350px]"
        />
      </div>
    </div>
  );
}
