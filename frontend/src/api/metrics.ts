import { get } from "./client";

export type DeploymentPoint = {
  date: string;
  count: number;
};

export type PerformanceLevel = "elite" | "high" | "medium" | "low";

/**
 * Each DORA metric from the backend has these fields.
 * Note: The backend uses "label" (not "unit") — see metrics.py lines 155-174.
 */
export type DoraMetric = {
  value: number;
  label: string;
  performance: PerformanceLevel;
};

/**
 * Matches the dummy response shape from GET /metrics/dora/{repo_id}.
 * Note: The backend uses "mean_time_to_restore" (not "mean_time_to_recovery").
 */
export type DoraMetrics = {
  repo_id: string;
  period_days: number;
  deployment_frequency: DoraMetric;
  lead_time_for_changes: DoraMetric;
  change_failure_rate: DoraMetric;
  mean_time_to_restore: DoraMetric;
  deployment_history?: DeploymentPoint[];
};

export function getDoraMetrics(repoId: string, days = 30) {
  return get<DoraMetrics>(`/metrics/dora/${repoId}?days=${days}`);
}
