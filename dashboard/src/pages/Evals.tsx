import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getComparisons } from "@/api";
import { verdictBadge } from "@/pages/Overview";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/States";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDelta, formatTime, shortModel } from "@/lib/format";
import type { ComparisonCard } from "@/types";

export function Evals() {
  const [rows, setRows] = useState<ComparisonCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getComparisons()
      .then((body) => {
        if (!cancelled) setRows(body.comparisons);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Request failed");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <ErrorState message={error} />;
  if (!rows) return <LoadingBlock />;
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No comparisons yet"
        body="Run llmwatch eval run, or seed the demo to see the scripted 70B and 3B swaps."
      />
    );
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="font-display text-3xl tracking-tight sm:text-4xl">Eval runs</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Each card is model B minus model A on the same suite. The gate fails on a significant negative mean or any
          pass-to-fail flip.
        </p>
      </header>
      <div className="grid gap-4 lg:grid-cols-2">
        {rows.map((row) => (
          <Link key={row.id} to={`/evals/${row.id}`} className="block">
            <Card className={row.failed_gate ? "border-[#e7c4be]" : ""}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <CardTitle>{row.name}</CardTitle>
                  {verdictBadge(row)}
                </div>
                <CardDescription>
                  {row.suite_name} · {formatTime(row.created_at)}
                  {row.synthetic ? " · synthetic demo" : ""}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>
                  <span className="text-muted-foreground">{row.label_a || "A"} </span>
                  {shortModel(row.model_a)} {row.mean_a.toFixed(3)}
                  <span className="text-muted-foreground"> → {row.label_b || "B"} </span>
                  {shortModel(row.model_b)} {row.mean_b.toFixed(3)}
                </p>
                <p className="nums">
                  delta {formatDelta(row.delta)} · CI [{row.ci_low.toFixed(3)}, {row.ci_high.toFixed(3)}] · flips {row.pass_flips}
                </p>
                {row.narrative ? <p className="text-muted-foreground">{row.narrative}</p> : null}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
