import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getComparisons, getSummary, getTimeseries } from "@/api";
import { TrendChart } from "@/components/Charts";
import { ErrorState, LoadingBlock } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatMs, formatPct, formatTokens, formatUsd, shortModel } from "@/lib/format";
import { gateCopy, gateVerdict } from "@/lib/regression";
import type { ComparisonCard, MetricsSummary, Timeseries } from "@/types";

export function Overview() {
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [series, setSeries] = useState<Timeseries | null>(null);
  const [comparisons, setComparisons] = useState<ComparisonCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getSummary(), getTimeseries(), getComparisons()])
      .then(([nextSummary, nextSeries, nextComparisons]) => {
        if (cancelled) return;
        setSummary(nextSummary);
        setSeries(nextSeries);
        setComparisons(nextComparisons.comparisons);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Request failed");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <ErrorState message={error} />;
  if (!summary || !series || !comparisons) return <LoadingBlock />;

  const regression = comparisons.find((item) => item.failed_gate);
  const empty = summary.calls === 0;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl tracking-tight sm:text-4xl">Call ledger</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Latency percentiles use successful calls only. Cost is the bundled price table applied to stored token counts,
          not a provider invoice.
        </p>
      </header>

      {empty ? (
        <Card>
          <CardHeader>
            <CardTitle>The ledger is empty</CardTitle>
            <CardDescription>Seed the synthetic demo with llmwatch seed, or record a call with the SDK.</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Stat label="Calls" value={formatTokens(summary.calls)} detail={`${formatTokens(summary.errors)} errors`} />
            <Stat label="Spend" value={formatUsd(summary.cost_usd)} detail="price table, not an invoice" />
            <Stat label="p50 latency" value={formatMs(summary.latency_p50_ms)} detail={`p95 ${formatMs(summary.latency_p95_ms)}`} />
            <Stat label="Error rate" value={formatPct(summary.error_rate)} detail="timeouts, 429s, 5xx, 400s" />
          </section>

          {regression ? (
            <Link to={`/evals/${regression.id}`} className="block">
              <Card className="border-[#e7c4be] bg-[#fdeceb]">
                <CardHeader>
                  <CardTitle className="text-[#9f2d20]">Gate failed · {regression.name}</CardTitle>
                  <CardDescription className="text-[#7a3b34]">
                    Mean score {regression.mean_a.toFixed(2)} → {regression.mean_b.toFixed(2)}. {regression.pass_flips} pass-to-fail
                    flip{regression.pass_flips === 1 ? "" : "s"}. Open the comparison.
                  </CardDescription>
                </CardHeader>
              </Card>
            </Link>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>Daily shape</CardTitle>
              <CardDescription>
                One line per model. Gaps are days with no successful calls for that model.{" "}
                {series.models.map((model) => `${shortModel(model)} = ${model}`).join(" · ")}
              </CardDescription>
            </CardHeader>
            <CardContent className="min-w-0">
              <Tabs defaultValue="latency">
                <TabsList className="max-w-full overflow-x-auto">
                  <TabsTrigger value="latency">Latency</TabsTrigger>
                  <TabsTrigger value="cost">Cost</TabsTrigger>
                  <TabsTrigger value="tokens">Tokens</TabsTrigger>
                </TabsList>
                <TabsContent value="latency">
                  <TrendChart series={series} metric="latency" />
                </TabsContent>
                <TabsContent value="cost">
                  <TrendChart series={series} metric="cost" />
                </TabsContent>
                <TabsContent value="tokens">
                  <TrendChart series={series} metric="tokens" />
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>By model</CardTitle>
              <CardDescription>Mean cost × 1,000 is a projection from this slice, not a bill.</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead>Calls</TableHead>
                    <TableHead className="hidden sm:table-cell">Errors</TableHead>
                    <TableHead>p50</TableHead>
                    <TableHead className="hidden md:table-cell">Tokens</TableHead>
                    <TableHead>Spend</TableHead>
                    <TableHead className="hidden lg:table-cell">$ / 1k calls</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {summary.by_model.map((model) => (
                    <TableRow key={model.model}>
                      <TableCell className="max-w-[7.5rem] truncate font-medium sm:max-w-[12rem]">{model.model}</TableCell>
                      <TableCell className="nums">{formatTokens(model.calls)}</TableCell>
                      <TableCell className="hidden sm:table-cell">{formatPct(model.error_rate)}</TableCell>
                      <TableCell className="nums">{formatMs(model.latency_p50_ms)}</TableCell>
                      <TableCell className="nums hidden md:table-cell">{formatTokens(model.tokens)}</TableCell>
                      <TableCell className="nums">{formatUsd(model.cost_usd)}</TableCell>
                      <TableCell className="nums hidden lg:table-cell">{formatUsd(model.mean_cost_per_1k)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription className="nums text-[11px] tracking-[0.14em] uppercase">{label}</CardDescription>
        <CardTitle className="nums text-xl whitespace-nowrap sm:text-2xl">{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">{detail}</CardContent>
    </Card>
  );
}

export function verdictBadge(comparison: { failed_gate: boolean; significant_improvement: boolean }) {
  const copy = gateCopy(gateVerdict(comparison));
  const variant = copy.tone === "bad" ? "destructive" : copy.tone === "good" ? "default" : "secondary";
  return <Badge variant={variant}>{copy.title}</Badge>;
}
