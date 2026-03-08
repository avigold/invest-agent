import { useEffect, useRef, useState } from "react";
import {
  createChart,
  AreaSeries,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
} from "lightweight-charts";
import { useChartData } from "@/lib/queries";
import PriceHeader, { type LatestPrice } from "./PriceHeader";
import type { MarketStatusData } from "./MarketStatus";

interface ChartPoint {
  date: string;
  value: number;
}

interface ChartResponse {
  ticker: string;
  currency: string;
  period: string;
  points: ChartPoint[];
  latest: LatestPrice | null;
  market_status: MarketStatusData;
}

const PERIODS = ["1W", "1M", "3M", "6M", "1Y", "5Y"] as const;

export default function StockChart({ ticker }: { ticker: string }) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const [period, setPeriod] = useState("1y");
  const { data, isLoading: loading } = useChartData<ChartResponse>(ticker, period);
  const [crosshairPrice, setCrosshairPrice] = useState<{
    date: string;
    value: number;
  } | null>(null);

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
      watermark: { visible: false },
      rightPriceScale: {
        borderColor: "#374151",
        minimumWidth: 80,
        entireTextOnly: true,
      },
      timeScale: {
        borderColor: "#374151",
        timeVisible: false,
      },
      width: chartContainerRef.current.clientWidth,
      height: window.innerWidth >= 768 ? 400 : 280,
    });

    const series = chart.addSeries(AreaSeries, {
      topColor: "rgba(59, 130, 246, 0.4)",
      bottomColor: "rgba(59, 130, 246, 0.0)",
      lineColor: "#3b82f6",
      lineWidth: 2,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderColor: "#3b82f6",
      crosshairMarkerBackgroundColor: "#1e3a5f",
      priceFormat: {
        type: "price",
        precision: 2,
        minMove: 0.01,
      },
    });

    chartRef.current = chart;
    seriesRef.current = series;

    // Crosshair handler
    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      if (!param.time || !param.point) {
        setCrosshairPrice(null);
        return;
      }
      const seriesData = param.seriesData.get(series);
      if (seriesData && "value" in seriesData) {
        setCrosshairPrice({
          date: String(param.time),
          value: (seriesData as { value: number }).value,
        });
      }
    });

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
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
        height: window.innerWidth >= 768 ? 400 : 280,
      });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  // Sync query data to chart
  useEffect(() => {
    if (data && seriesRef.current && data.points.length > 0) {
      seriesRef.current.setData(
        data.points.map((p) => ({ time: p.date, value: p.value }))
      );
      chartRef.current?.timeScale().fitContent();
    }
  }, [data]);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5 mb-8">
      {/* Price header */}
      {data?.latest && (
        <PriceHeader
          latest={data.latest}
          marketStatus={data.market_status}
          crosshairPrice={crosshairPrice}
          currency={data.currency}
        />
      )}

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
        {loading && !data && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="text-sm text-gray-500">Loading chart...</div>
          </div>
        )}
        <div
          ref={chartContainerRef}
          className="w-full h-[280px] md:h-[400px]"
        />
        {data && data.points.length === 0 && !loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-sm text-gray-500">
              No price data available for this period
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
