import { get } from "./client";

export type PerformanceLevel = "elite" | "high" | "medium" | "low";

export type MetricValue = {
	value: number | string;
	unit?: string;
	performance?: PerformanceLevel;
};

export type DeploymentPoint = {
	date?: string;
	week?: string;
	label?: string;
	count?: number;
	deployments?: number;
	value?: number;
};

export type DoraMetrics = {
	deployment_frequency?: MetricValue;
	lead_time_for_changes?: MetricValue;
	mean_time_to_recovery?: MetricValue;
	change_failure_rate?: MetricValue;

	deploymentFrequency?: number | string;
	leadTimeForChanges?: number | string;
	mttr?: number | string;
	changeFailureRate?: number | string;

	deployment_history?: DeploymentPoint[];
	deploymentHistory?: DeploymentPoint[];
};

export function getDoraMetrics(repoId: string, days = 30) {
	return get<DoraMetrics>(`/metrics/dora/${repoId}?days=${days}`);
}
