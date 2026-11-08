export function formatUsd(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs === 0) return "$0";
  if (abs < 0.01) return `$${value.toFixed(6)}`;
  if (abs < 1) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatMs(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

export function formatTokens(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatDelta(value: number): string {
  const sign = value > 0 ? "+" : "";
  return sign + value.toFixed(3);
}

export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const formatted = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    hourCycle: "h23",
  }).format(date);
  return `${formatted} UTC`;
}

export function shortModel(model: string): string {
  if (model.includes("70b")) return "70B";
  if (model.includes("8b")) return "8B";
  if (model.includes("3b")) return "3B";
  return model;
}

export const MODEL_COLORS: Record<string, string> = {
  "llama-3.1-8b-instant": "#0c6b58",
  "llama-3.3-70b-versatile": "#b45309",
  "llama-3.2-3b-preview": "#3f5f8a",
};

const FALLBACK_COLORS = ["#0c6b58", "#b45309", "#3f5f8a", "#9f2d20", "#5b4b8a"];

export function modelColor(model: string, index: number): string {
  return MODEL_COLORS[model] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}
