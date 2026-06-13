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
	background: "#ffffff",
	border: "1px solid #dbe3ef",
	borderRadius: "10px",
	boxShadow: "0 8px 24px rgba(15, 23, 42, 0.08)",
	color: "#0f172a",
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
					<CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
					<XAxis dataKey="label" stroke="#64748b" tickLine={false} axisLine={false} />
					<YAxis stroke="#64748b" tickLine={false} axisLine={false} allowDecimals={false} />
					<Tooltip contentStyle={tooltipStyle} />
					<Bar dataKey="count" fill="#2563eb" radius={[6, 6, 0, 0]} />
				</BarChart>
			</ResponsiveContainer>
		</div>
	);
}
