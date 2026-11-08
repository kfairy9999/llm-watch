import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, getCall } from "@/api";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatMs, formatTime, formatTokens, formatUsd } from "@/lib/format";
import type { CallDetail as CallRecord } from "@/types";

export function CallDetail() {
  const { id = "" } = useParams();
  const [call, setCall] = useState<CallRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setCall(null);
    setError(null);
    setMissing(false);
    getCall(id)
      .then((row) => {
        if (!cancelled) setCall(row);
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
  if (missing) return <EmptyState title="Call not found" body="That id is not in this ledger." />;
  if (!call) return <LoadingBlock />;

  return (
    <div className="space-y-5">
      <Link to="/calls" className="text-sm text-primary hover:underline">
        Back to calls
      </Link>
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={call.status === "ok" ? "secondary" : "destructive"}>{call.status}</Badge>
          <Badge variant="outline">{call.data_label}</Badge>
          {call.route ? <Badge variant="outline">{call.route}</Badge> : null}
        </div>
        <h1 className="font-display text-2xl tracking-tight break-words sm:text-3xl">{call.model}</h1>
        <p className="nums text-sm text-muted-foreground">
          {formatTime(call.created_at)} · {call.provider} · {call.attempts} attempt{call.attempts === 1 ? "" : "s"}
          {call.http_status ? ` · HTTP ${call.http_status}` : ""}
        </p>
      </header>
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Latency" value={formatMs(call.latency_ms)} />
        <Metric label="Tokens" value={`${formatTokens(call.prompt_tokens)} in / ${formatTokens(call.completion_tokens)} out`} />
        <Metric label="Cost" value={formatUsd(call.cost_usd)} />
        <Metric label="Token source" value={call.token_source} />
      </section>
      {call.error_message ? (
        <Card className="border-[#e7c4be] bg-[#fdeceb]">
          <CardHeader>
            <CardTitle className="text-[#9f2d20]">{call.error_type ?? "error"}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">{call.error_message}</CardContent>
        </Card>
      ) : null}
      <section className="space-y-3">
        <h2 className="font-display text-2xl">Prompt</h2>
        {call.messages.map((message, index) => (
          <article key={`${message.role ?? "msg"}-${index}`} className="rounded-xl bg-card p-4 ring-1 ring-foreground/10">
            <p className="nums text-[11px] tracking-[0.14em] text-muted-foreground uppercase">{message.role ?? "message"}</p>
            <pre className="mt-2 max-h-80 max-w-full overflow-auto text-sm leading-relaxed break-words whitespace-pre-wrap">
              {typeof message.content === "string" ? message.content : JSON.stringify(message.content, null, 2)}
            </pre>
          </article>
        ))}
      </section>
      <section className="space-y-3">
        <h2 className="font-display text-2xl">Response</h2>
        <article className="rounded-xl bg-card p-4 ring-1 ring-foreground/10">
          <pre className="max-h-96 max-w-full overflow-auto text-sm leading-relaxed break-words whitespace-pre-wrap">
            {call.response_text || "(no assistant text)"}
          </pre>
        </article>
      </section>
      <details className="rounded-xl bg-card p-4 ring-1 ring-foreground/10">
        <summary className="cursor-pointer text-sm font-medium">Raw payload</summary>
        <pre className="mt-3 max-h-96 max-w-full overflow-auto text-xs leading-relaxed break-words whitespace-pre-wrap">
          {JSON.stringify({ response: call.response, metadata: call.metadata }, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <p className="nums text-[11px] tracking-[0.14em] text-muted-foreground uppercase">{label}</p>
        <p className="nums text-base break-words sm:text-lg">{value}</p>
      </CardHeader>
    </Card>
  );
}
