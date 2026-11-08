import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMs, formatTokens, formatUsd, modelColor, shortModel } from "@/lib/format";
import type { Timeseries } from "@/types";

type Metric = "latency" | "cost" | "tokens";

export function TrendChart({ series, metric }: { series: Timeseries; metric: Metric }) {
  const rows = series.points.map((point) => {
    const row: Record<string, string | number | null> = { date: point.date.slice(5) };
    for (const model of series.models) {
      const bucket = point.by_model[model];
      const key = shortModel(model);
      if (!bucket) {
        row[key] = null;
        continue;
      }
      if (metric === "latency") row[key] = bucket.latency_p50_ms;
      else if (metric === "cost") row[key] = bucket.cost_usd;
      else row[key] = bucket.tokens;
    }
    return row;
  });
  const keys = series.models.map((model) => shortModel(model));
  const phone = usePhoneWidth();

  return (
    <div className="h-52 w-full min-w-0 sm:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: phone ? 4 : 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#e4dccb" vertical={false} />
          <XAxis dataKey="date" tick={{ fontSize: phone ? 10 : 12, fill: "#5e584e" }} tickLine={false} axisLine={false} />
          <YAxis
            domain={[0, "auto"]}
            tick={{ fontSize: phone ? 10 : 12, fill: "#5e584e" }}
            tickLine={false}
            axisLine={false}
            width={phone ? 58 : 64}
            tickFormatter={(value: number) => formatTick(metric, value)}
          />
          <Tooltip
            formatter={(value, name) => [formatTick(metric, Number(value)), String(name)]}
            contentStyle={{ background: "#fffdf8", border: "1px solid #e4dccb", borderRadius: 8, fontSize: 12 }}
          />
          <Legend />
          {keys.map((key, index) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={modelColor(series.models[index] ?? key, index)}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function usePhoneWidth(): boolean {
  const [phone, setPhone] = useState(phoneWidth);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(max-width: 639px)");
    const update = () => setPhone(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return phone;
}

function phoneWidth(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(max-width: 639px)").matches;
}

function formatTick(metric: Metric, value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (metric === "latency") return formatMs(value);
  if (metric === "cost") return formatUsd(value);
  return formatTokens(value);
}
