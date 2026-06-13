import { get } from "./client";

export type Review = {
	id: string;
	pr_id?: string;
	pr_number?: number;
	pull_request_number?: number;
	pr_title?: string;
	status?: string;
	risk_score?: number;
	summary?: string;
	posted_to_github?: boolean;
	created_at?: string;
	updated_at?: string;
	completed_at?: string;
};

export function getRecentReviews() {
	return get<Review[]>("/reviews/");
}
