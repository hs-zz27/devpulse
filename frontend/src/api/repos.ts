import { get, post } from "./client";

export type Repo = {
	id: string;
	owner_id?: string;
	github_repo_id: number;
	full_name: string;
	webhook_id?: number | string | null;
	webhook_secret?: string | null;
	is_active: boolean;
	created_at?: string;
};

export type GitHubRepo = {
	id: number;
	github_repo_id?: number;
	name: string;
	full_name: string;
	private: boolean;
	html_url?: string;
	can_connect?: boolean;
	permissions?: {
		admin?: boolean;
		maintain?: boolean;
		push?: boolean;
		triage?: boolean;
		pull?: boolean;
	};
};

export function listRepos() {
	return get<Repo[]>("/repos/");
}

export function listGitHubRepos() {
	return get<GitHubRepo[]>("/repos/github");
}

export function connectRepo(repo: { github_repo_id: number; full_name: string }) {
	return post<Repo>("/repos/connect", repo);
}
