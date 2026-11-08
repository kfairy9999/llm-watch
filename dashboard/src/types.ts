export type Meta = {
  version: string;
  dataset_label: string | null;
  frozen_at: string | null;
  disclaimer: string | null;
  price_note: string;
  synthetic_calls: number;
  recorded_calls: number;
  synthetic_comparisons: number;
  recorded_comparisons: number;
};

export type CallSummary = {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  endpoint: string;
  prompt_preview: string;
  response_preview: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  token_source: string;
  latency_ms: number;
  cost_usd: number;
  price_source: string;
  status: string;
  error_type: string | null;
  error_message: string | null;
  http_status: number | null;
  attempts: number;
  synthetic: boolean;
  data_label: string;
  streaming: boolean;
  route: string | null;
  metadata: Record<string, unknown>;
};

export type CallDetail = CallSummary & {
  messages: Array<{ role?: string; content?: unknown }>;
  response_text: string;
  response: unknown;
};

export type CallPage = {
  total: number;
  limit: number;
  offset: number;
  calls: CallSummary[];
};

export type ModelSummary = {
  model: string;
  calls: number;
  errors: number;
  error_rate: number;
  cost_usd: number;
  mean_cost_per_1k: number;
  tokens: number;
  latency_p50_ms: number | null;
  synthetic_calls: number;
};

export type MetricsSummary = {
  calls: number;
  errors: number;
  error_rate: number;
  cost_usd: number;
  prompt_tokens: number;
  completion_tokens: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  latency_basis: string;
  by_model: ModelSummary[];
};

export type ModelPoint = {
  calls: number;
  cost_usd: number;
  tokens: number;
  latency_p50_ms: number | null;
};

export type DayPoint = {
  date: string;
  calls: number;
  errors: number;
  cost_usd: number;
  tokens: number;
  latency_p50_ms: number | null;
  by_model: Record<string, ModelPoint>;
};

export type Timeseries = {
  bucket: string;
  data_label: string;
  synthetic: boolean;
  models: string[];
  total_calls: number;
  points: DayPoint[];
};

export type ScorerDetail = {
  type: string;
  score: number;
  passed: boolean;
  detail: string;
};

export type ComparisonTest = {
  test_id: string;
  description: string;
  prompt: string;
  output_a: string;
  output_b: string;
  score_a: number;
  score_b: number;
  delta: number;
  passed_a: boolean;
  passed_b: boolean;
  flag: "regression" | "improvement" | "unchanged";
  scorers_a: ScorerDetail[];
  scorers_b: ScorerDetail[];
  error_a: string | null;
  error_b: string | null;
};

export type ComparisonCard = {
  id: string;
  name: string;
  created_at: string;
  suite_name: string;
  run_a_id: string;
  run_b_id: string;
  model_a: string;
  model_b: string;
  label_a: string;
  label_b: string;
  mean_a: number;
  mean_b: number;
  delta: number;
  ci_low: number;
  ci_high: number;
  significant_regression: boolean;
  significant_improvement: boolean;
  pass_rate_a: number;
  pass_rate_b: number;
  pass_flips: number;
  failed_gate: boolean;
  provenance: string;
  narrative: string | null;
  n_tests: number;
  synthetic: boolean;
};

export type ComparisonDetail = ComparisonCard & {
  alpha: number;
  n_boot: number;
  seed: number;
  pass_gains: number;
  provenance_note: string;
  metrics_simulated: boolean;
  mean_latency_a: number;
  mean_latency_b: number;
  mean_cost_a: number;
  mean_cost_b: number;
  price_note: string;
  method: string;
  tests: ComparisonTest[];
};
