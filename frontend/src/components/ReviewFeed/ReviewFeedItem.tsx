import { Review } from "../../api/reviews";

type ReviewFeedItemProps = {
	review: Review;
	animate?: boolean;
};

function getRiskColor(score?: number) {
	if (score === undefined || score === null) return "risk neutral";
	if (score <= 30) return "risk green";
	if (score <= 60) return "risk yellow";
	if (score <= 80) return "risk orange";
	return "risk red";
}

function timeAgo(dateValue?: string) {
	if (!dateValue) return "just now";

	const date = new Date(dateValue);
	const seconds = Math.max(1, Math.floor((Date.now() - date.getTime()) / 1000));

	if (seconds < 60) return `${seconds}s ago`;

	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m ago`;

	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;

	const days = Math.floor(hours / 24);
	return `${days}d ago`;
}

export default function ReviewFeedItem({ review, animate = false }: ReviewFeedItemProps) {
	const riskScore = review.risk_score ?? 0;
	const prNumber = review.pr_number ?? review.pull_request_number ?? "—";
	const timestamp = review.completed_at ?? review.updated_at ?? review.created_at ?? undefined;

	return (
		<article className={animate ? "review-item newest" : "review-item"}>
			<div className="review-item-header">
				<strong>PR #{prNumber}</strong>
				<span className={getRiskColor(riskScore)}>Risk {riskScore}</span>
			</div>

			<p>{review.summary ?? review.pr_title ?? "Review update received."}</p>

			<span className="muted">{timeAgo(timestamp)}</span>
		</article>
	);
}
