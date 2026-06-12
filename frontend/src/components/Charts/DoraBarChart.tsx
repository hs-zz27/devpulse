import type { CSSProperties } from "react";
import { useEffect, useState } from "react";
import {
	Bar,
	BarChart,
	CartesianGrid,
	Cell,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { DeploymentPoint } from "../../api/metrics";

type DoraBarChartProps = {
	data: DeploymentPoint[];
};

const fallbackData: DeploymentPoint[] = [
	{ date: "Week 1", count: 3 },
	{ date: "Week 2", count: 5 },
	{ date: "Week 3", count: 4 },
	{ date: "Week 4", count: 8 },
];

function useDarkMode() {
	const [dark, setDark] = useState(
		() => document.documentElement.getAttribute("data-theme") === "dark",
	);

	useEffect(() => {
		const observer = new MutationObserver(() => {
			setDark(document.documentElement.getAttribute("data-theme") === "dark");
		});
		observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
		return () => observer.disconnect();
	}, []);

	return dark;
}

// Light mode palette
const LIGHT = {
	barDefault: "#2563eb",
	barHover: "#1d4ed8",
	axisStroke: "#64748b",
	gridStroke: "#e2e8f0",
	cursorFill: "rgba(37, 99, 235, 0.07)",
	tooltip: {
		background: "#ffffff",
		border: "1px solid #bfdbfe",
		borderRadius: "10px",
		boxShadow: "0 8px 24px rgba(15, 23, 42, 0.10)",
		color: "#0f172a",
		fontSize: "0.84rem",
		fontWeight: 600,
		padding: "8px 12px",
	} as CSSProperties,
};

// Dark mode palette
const DARK = {
	barDefault: "#58a6ff",
	barHover: "#79b8ff",
	axisStroke: "#8b949e",
	gridStroke: "#30363d",
	cursorFill: "rgba(88, 166, 255, 0.10)",
	tooltip: {
		background: "#21262d",
		border: "1px solid #1f4070",
		borderRadius: "10px",
		boxShadow: "0 8px 24px rgba(0, 0, 0, 0.40)",
		color: "#e6edf3",
		fontSize: "0.84rem",
		fontWeight: 600,
		padding: "8px 12px",
	} as CSSProperties,
};

export default function DoraBarChart({ data }: DoraBarChartProps) {
	const dark = useDarkMode();
	const theme = dark ? DARK : LIGHT;
	const chartData = data.length > 0 ? data : fallbackData;
	const [activeIndex, setActiveIndex] = useState<number | null>(null);

	return (
		<div className="chart-container">
			<ResponsiveContainer width="100%" height={280}>
				<BarChart
					data={chartData}
					onMouseLeave={() => setActiveIndex(null)}
				>
					<CartesianGrid strokeDasharray="3 3" stroke={theme.gridStroke} vertical={false} />
					<XAxis
						dataKey="date"
						stroke={theme.axisStroke}
						tick={{ fill: theme.axisStroke, fontSize: 12 }}
						tickLine={false}
						axisLine={false}
					/>
					<YAxis
						stroke={theme.axisStroke}
						tick={{ fill: theme.axisStroke, fontSize: 12 }}
						tickLine={false}
						axisLine={false}
						allowDecimals={false}
					/>
					<Tooltip
						contentStyle={theme.tooltip}
						cursor={{ fill: theme.cursorFill, radius: 6 }}
						formatter={(value: number) => [value, "Deployments"]}
						labelStyle={{ marginBottom: 2, fontWeight: 700 }}
					/>
					<Bar
						dataKey="count"
						radius={[6, 6, 0, 0]}
						onMouseEnter={(_, index) => setActiveIndex(index)}
					>
						{chartData.map((_, index) => (
							<Cell
								key={`cell-${index}`}
								fill={index === activeIndex ? theme.barHover : theme.barDefault}
								style={{ transition: "fill 0.15s ease" }}
							/>
						))}
					</Bar>
				</BarChart>
			</ResponsiveContainer>
		</div>
	);
}
