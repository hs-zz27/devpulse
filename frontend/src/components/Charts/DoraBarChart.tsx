import type { CSSProperties } from "react";
import {
	Bar,
	BarChart,
	CartesianGrid,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { DeploymentPoint } from "../../api/metrics";

type DoraBarChartProps = {
	data?: DeploymentPoint[];
};

const tooltipStyle: CSSProperties = {
	background: "var(--surface)",
	border: "1px solid var(--border)",
	borderRadius: "var(--radius-md)",
	boxShadow: "var(--shadow-md)",
	color: "var(--text)",
};

function normalizePoint(point: DeploymentPoint) {
	return {
		label: point.date ?? point.week ?? point.label ?? "—",
		count: point.count ?? point.deployments ?? point.value ?? 0,
	};
}

export default function DoraBarChart({ data = [] }: DoraBarChartProps) {
	const chartData =
		data.length > 0
			? data.map(normalizePoint)
			: [
					{ label: "Week 1", count: 0 },
					{ label: "Week 2", count: 0 },
					{ label: "Week 3", count: 0 },
					{ label: "Week 4", count: 0 },
				];

	return (
		<div className="chart-container">
			<ResponsiveContainer width="100%" height={280}>
				<BarChart data={chartData}>
					<CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
					<XAxis dataKey="label" stroke="var(--text-soft)" tickLine={false} axisLine={false} />
					<YAxis stroke="var(--text-soft)" tickLine={false} axisLine={false} allowDecimals={false} />
					<Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--surface-subtle)" }} />
					<Bar dataKey="count" fill="var(--blue)" radius={[6, 6, 0, 0]} />
				</BarChart>
			</ResponsiveContainer>
		</div>
	);
}
