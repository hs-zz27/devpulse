import { get } from "./client";

/**
 * Matches the dict shape returned by GET /reviews/ in reviews.py lines 112-122.
 * Note: No pr_number or pr_title — only pr_id (UUID FK).
 */
export type Review = {
  id: string;
  pr_id: string;
  status: string;
  risk_score: number;
  summary: string;
  completed_at: string | null;
  // Optional fields used by ReviewFeedItem
  pr_number?: number | string;
  pull_request_number?: number | string;
  pr_title?: string;
  updated_at?: string | null;
  created_at?: string | null;
};

export async function getRecentReviews(): Promise<Review[]> {
  const data = await get<Review[]>("/reviews/");
  return Array.isArray(data) ? data : [];
}
