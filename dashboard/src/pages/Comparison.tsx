import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, getComparison } from "@/api";
import { verdictBadge } from "@/pages/Overview";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDelta, formatMs, formatUsd } from "@/lib/format";
import { intervalSentence } from "@/lib/regression";
import type { ComparisonDetail, ComparisonTest } from "@/types";

export function Comparison() {
  const { id = "" } = useParams();
  const [row, setRow] = useState<ComparisonDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRow(null);
    setError(null);
    setMissing(false);
    getComparison(id)
      .then((body) => {
        if (!cancelled) setRow(body);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        if (reason instanceof ApiError && reason.status === 404) setMissing(true);
        else setError(reason instanceof Error ? reason.message : "Request failed");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) return <ErrorState message={error} />;
  if (missing) return <EmptyState title="Comparison not found" body="That eval run is not in this ledger." />;
  if (!row) return <LoadingBlock />;

  const latencyLabel = row.metrics_simulated ? "Simulated latency" : "Latency";
  const costLabel = row.metrics_simulated ? "Simulated cost" : "Cost";

  return (
    <div className="space-y-5">
      <Link to="/evals" className="text-sm text-primary hover:underline">
        Back to evals
      </Link>
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {verdictBadge(row)}
          {row.synthetic ? <Badge variant="outline">synthetic demo</Badge> : null}
          <Badge variant="outline">{row.provenance}</Badge>
        </div>
        <h1 className="font-display text-3xl tracking-tight md:text-4xl">{row.name}</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{row.provenance_note}</p>
        {row.narrative ? <p className="max-w-3xl text-sm">{row.narrative}</p> : null}
      </header>
      <Card className={row.failed_gate ? "border-[#e7c4be] bg-[#fff8f7]" : "bg-card"}>
        <CardContent className="pt-4 text-sm leading-relaxed">{intervalSentence(row)}</CardContent>
      </Card>
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Mean score" value={`${row.mean_a.toFixed(3)} → ${row.mean_b.toFixed(3)}`} />
        <Metric label="Pass rate" value={`${(row.pass_rate_a * 100).toFixed(0)}% → ${(row.pass_rate_b * 100).toFixed(0)}%`} />
        <Metric label={latencyLabel} value={`${formatMs(row.mean_latency_a)} → ${formatMs(row.mean_latency_b)}`} />
        <Metric label={costLabel} value={`${formatUsd(row.mean_cost_a)} → ${formatUsd(row.mean_cost_b)}`} />
      </section>
      <p className="text-xs text-muted-foreground">{row.price_note}</p>
      <div className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Test</TableHead>
              <TableHead>A</TableHead>
              <TableHead>B</TableHead>
              <TableHead>Delta</TableHead>
              <TableHead>Flag</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {row.tests.map((test) => (
              <TestRows key={test.test_id} test={test} open={open === test.test_id} onToggle={() => setOpen(open === test.test_id ? null : test.test_id)} modelA={row.model_a} modelB={row.model_b} />
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="max-w-3xl text-xs text-muted-foreground">{row.method}</p>
    </div>
  );
}

function TestRows({
  test,
  open,
  onToggle,
  modelA,
  modelB,
}: {
  test: ComparisonTest;
  open: boolean;
  onToggle: () => void;
  modelA: string;
  modelB: string;
}) {
  const tone =
    test.flag === "regression" ? "bg-[#fdeceb]" : test.flag === "improvement" ? "bg-[#e7f6ec]" : "";
  return (
    <>
      <TableRow className={tone}>
        <TableCell>
          <button type="button" className="text-left hover:underline" onClick={onToggle}>
            <span className="font-medium">{test.test_id}</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">{test.description}</span>
          </button>
        </TableCell>
        <TableCell className="nums">{test.score_a.toFixed(3)}</TableCell>
        <TableCell className="nums">{test.score_b.toFixed(3)}</TableCell>
        <TableCell className="nums">{formatDelta(test.delta)}</TableCell>
        <TableCell>
          {test.flag === "unchanged" ? (
            <span className="text-xs text-muted-foreground">unchanged</span>
          ) : (
            <Badge variant={test.flag === "regression" ? "destructive" : "default"}>{test.flag}</Badge>
          )}
        </TableCell>
      </TableRow>
      {open ? (
        <TableRow className={tone}>
          <TableCell colSpan={5}>
            <div className="grid gap-4 py-2 lg:grid-cols-2">
              <Output title={modelA} text={test.output_a} scorers={test.scorers_a} error={test.error_a} />
              <Output title={modelB} text={test.output_b} scorers={test.scorers_b} error={test.error_b} />
            </div>
            <p className="mt-3 text-xs text-muted-foreground whitespace-pre-wrap">{test.prompt}</p>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

function Output({
  title,
  text,
  scorers,
  error,
}: {
  title: string;
  text: string;
  scorers: ComparisonTest["scorers_a"];
  error: string | null;
}) {
  return (
    <div>
      <p className="text-xs font-medium">{title}</p>
      <pre className="mt-1 max-h-48 overflow-auto text-xs whitespace-pre-wrap">{text || "(empty)"}</pre>
      {error ? <p className="mt-1 text-xs text-[#9f2d20]">{error}</p> : null}
      <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
        {scorers.map((scorer, index) => (
          <li key={`${scorer.type}-${index}`}>
            {scorer.type}: {scorer.passed ? "pass" : "fail"} — {scorer.detail}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-xs font-normal text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent className="nums">{value}</CardContent>
    </Card>
  );
}
