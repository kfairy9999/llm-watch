import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function LoadingBlock() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  const demo = import.meta.env.VITE_DEMO_STATIC === "1";
  return (
    <Card>
      <CardHeader>
        <CardTitle>{demo ? "This page did not load" : "The API did not respond"}</CardTitle>
        <CardDescription>{message}</CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        {demo ? (
          "The static demo file for this view is missing. Reload the page."
        ) : (
          <>
            Start the ledger with <code className="nums">llmwatch serve --port 8491</code> and reload this page.
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{body}</CardDescription>
      </CardHeader>
    </Card>
  );
}
