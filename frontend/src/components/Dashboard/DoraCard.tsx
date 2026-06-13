import { useEffect, useMemo, useState } from "react";
import { PerformanceLevel } from "../../api/metrics";

type DoraCardProps = {
	label: string;
	value: number | string;
	unit?: string;
	performance?: PerformanceLevel;
};

function isNumeric(value: number | string) {
	return typeof value === "number" || !Number.isNaN(Number(value));
}

export default function DoraCard({
	label,
	value,
	unit,
	performance = "medium",
}: DoraCardProps) {
	const numericValue = useMemo(() => Number(value), [value]);
	const [displayValue, setDisplayValue] = useState<number | string>(isNumeric(value) ? 0 : value);

	useEffect(() => {
		if (!isNumeric(value)) {
			setDisplayValue(value);
			return;
		}

		let frame = 0;
		const totalFrames = 20;
		let animationFrame = 0;

		function tick() {
			frame += 1;

			const progress = Math.min(frame / totalFrames, 1);
			const eased = 1 - Math.pow(1 - progress, 3);
			const next = numericValue * eased;

			setDisplayValue(Number.isInteger(numericValue) ? Math.round(next) : next.toFixed(1));

			if (progress < 1) {
				animationFrame = requestAnimationFrame(tick);
			}
		}

		animationFrame = requestAnimationFrame(tick);

		return () => cancelAnimationFrame(animationFrame);
	}, [numericValue, value]);

	return (
		<article className="dora-card">
			<div className="card-topline">
				<span>{label}</span>
				<span className={`performance-badge ${performance}`}>{performance}</span>
			</div>

			<div className="metric-value">
				{displayValue}
				{unit && <span>{unit}</span>}
			</div>
		</article>
	);
}
