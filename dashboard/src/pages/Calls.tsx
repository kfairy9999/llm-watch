import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getCalls, getModels } from "@/api";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { buildCallsQuery } from "@/lib/filters";
import { formatMs, formatTime, formatTokens, formatUsd } from "@/lib/format";
import type { CallPage } from "@/types";

const PAGE = 25;

export function Calls() {
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [appliedQ, setAppliedQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<CallPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedQ(q.trim());
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    let cancelled = false;
    getModels()
      .then((body) => {
        if (!cancelled) setModels(body.models);
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getCalls(buildCallsQuery({ model, status, q: appliedQ, limit: PAGE, offset }))
      .then((body) => {
        if (!cancelled) {
          setPage(body);
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Request failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [model, status, appliedQ, offset]);

  const total = page?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = offset + (page?.calls.length ?? 0);

  return (
    <div className="space-y-5">
      <header>
        <h1 className="font-display text-3xl tracking-tight sm:text-4xl">Calls</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Filter the ledger by model, status, or a phrase in the prompt or reply.
        </p>
      </header>
      <div className="flex flex-col gap-2 md:flex-row">
        <Input
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder="Search prompts and replies"
          aria-label="Search prompts and replies"
          className="min-h-11 bg-card text-base md:min-h-8 md:max-w-sm md:text-sm"
        />
        <select
          aria-label="Model"
          value={model}
          onChange={(event) => {
            setModel(event.target.value);
            setOffset(0);
          }}
          className="h-11 w-full rounded-lg border border-input bg-card px-2 text-base md:h-8 md:w-auto md:text-sm"
        >
          <option value="">All models</option>
          {models.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <select
          aria-label="Status"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setOffset(0);
          }}
          className="h-11 w-full rounded-lg border border-input bg-card px-2 text-base md:h-8 md:w-auto md:text-sm"
        >
          <option value="">Any status</option>
          <option value="ok">ok</option>
          <option value="error">error</option>
        </select>
      </div>
      {error ? <ErrorState message={error} /> : null}
      {loading && !page ? <LoadingBlock /> : null}
      {page && page.calls.length === 0 ? (
        <EmptyState
          title={appliedQ || model || status ? "No calls match these filters" : "The ledger is empty"}
          body={
            appliedQ || model || status
              ? "Clear a filter or search for a different phrase."
              : "Seed the demo or record a call with the SDK."
          }
        />
      ) : null}
      {page && page.calls.length > 0 ? (
        <>
          <div className="space-y-2 md:hidden">
            {page.calls.map((call) => (
              <Link
                key={call.id}
                to={`/calls/${call.id}`}
                className="block rounded-xl bg-card p-3 ring-1 ring-foreground/10"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 truncate text-sm font-medium">{call.model}</p>
                  <span className="flex shrink-0 gap-1">
                    <Badge variant={call.status === "ok" ? "secondary" : "destructive"}>{call.status}</Badge>
                    {call.synthetic ? <Badge variant="outline">Demo</Badge> : null}
                  </span>
                </div>
                <p className="mt-1 line-clamp-3 text-sm">{call.prompt_preview || "(empty prompt)"}</p>
                <p className="nums mt-2 text-xs text-muted-foreground">
                  {formatTime(call.created_at)} · {formatMs(call.latency_ms)} · {formatUsd(call.cost_usd)}
                  {call.route ? ` · ${call.route}` : ""}
                </p>
              </Link>
            ))}
          </div>
          <div className="hidden rounded-xl bg-card ring-1 ring-foreground/10 md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Model</TableHead>
                <TableHead className="hidden md:table-cell">Route</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden sm:table-cell">Latency</TableHead>
                <TableHead className="hidden lg:table-cell">Tokens</TableHead>
                <TableHead>Cost</TableHead>
                <TableHead>Prompt</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {page.calls.map((call) => (
                <TableRow key={call.id}>
                  <TableCell className="nums text-xs whitespace-nowrap">{formatTime(call.created_at)}</TableCell>
                  <TableCell className="max-w-[10rem] truncate text-xs">{call.model}</TableCell>
                  <TableCell className="hidden md:table-cell text-xs">{call.route ?? "—"}</TableCell>
                  <TableCell>
                    <Badge variant={call.status === "ok" ? "secondary" : "destructive"}>{call.status}</Badge>
                    {call.synthetic ? (
                      <Badge variant="outline" className="ml-1">
                        Demo
                      </Badge>
                    ) : null}
                  </TableCell>
                  <TableCell className="nums hidden sm:table-cell">{formatMs(call.latency_ms)}</TableCell>
                  <TableCell className="nums hidden lg:table-cell">{formatTokens(call.total_tokens)}</TableCell>
                  <TableCell className="nums">{formatUsd(call.cost_usd)}</TableCell>
                  <TableCell className="max-w-[18rem] truncate">
                    <Link to={`/calls/${call.id}`} className="hover:underline">
                      {call.prompt_preview || "(empty prompt)"}
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm md:px-3 md:py-3">
            <p className="nums text-muted-foreground">
              {from}–{to} of {total}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="min-h-11 md:min-h-8"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                className="min-h-11 md:min-h-8"
                disabled={offset + PAGE >= total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
