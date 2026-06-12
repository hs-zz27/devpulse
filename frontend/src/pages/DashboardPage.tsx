import { useEffect, useMemo, useState } from "react";
import { CurrentUser, getMe } from "../api/auth";
import { DoraMetrics, getDoraMetrics } from "../api/metrics";
import {
	GitHubRepo,
	Repo,
	connectRepo,
	listGitHubRepos,
	listRepos,
} from "../api/repos";
import { Review, getRecentReviews } from "../api/reviews";
import DoraBarChart from "../components/Charts/DoraBarChart";
import DoraCard from "../components/Dashboard/DoraCard";
import ReviewFeedItem from "../components/ReviewFeed/ReviewFeedItem";
import { useSSE } from "../hooks/useSSE";

function repoLabel(repo: Repo | GitHubRepo) {
	return repo.full_name;
}

function hasAdminPermission(repo: GitHubRepo) {
	return Boolean(repo.permissions?.admin);
}

function getMetric(metrics: DoraMetrics | null, key: keyof DoraMetrics, fallback = "—") {
	const metric = metrics?.[key];

	if (metric && typeof metric === "object" && "value" in metric) {
		return {
			value: metric.value,
			unit: metric.label ?? "",
			performance: metric.performance ?? "medium",
		};
	}

	return {
		value: typeof metric === "number" || typeof metric === "string" ? metric : fallback,
		unit: "",
		performance: "medium" as const,
	};
}

export default function DashboardPage() {
	const [user, setUser] = useState<CurrentUser | null>(null);
	const [repos, setRepos] = useState<Repo[]>([]);
	const [githubRepos, setGithubRepos] = useState<GitHubRepo[]>([]);
	const [selectedRepoId, setSelectedRepoId] = useState<string | null>(null);
	const [reviews, setReviews] = useState<Review[]>([]);
	const [metrics, setMetrics] = useState<DoraMetrics | null>(null);
	const [loading, setLoading] = useState(true);
	const [loadingGithubRepos, setLoadingGithubRepos] = useState(false);
	const [connectingRepoId, setConnectingRepoId] = useState<number | null>(null);
	const [error, setError] = useState<string | null>(null);

	const { latestEvent, connected } = useSSE<Review>("/api/reviews/stream", true);

	useEffect(() => {
		async function bootstrap() {
			try {
				setLoading(true);
				setError(null);

				const [currentUser, repoList, recentReviews] = await Promise.all([
					getMe(),
					listRepos(),
					getRecentReviews(),
				]);

				setUser(currentUser);
				setRepos(repoList);
				setReviews(recentReviews);
				setSelectedRepoId(repoList[0]?.id ? String(repoList[0].id) : null);
			} catch (err) {
				setError(err instanceof Error ? err.message : "Unable to load dashboard");
			} finally {
				setLoading(false);
			}
		}

		bootstrap();
	}, []);

	useEffect(() => {
		if (!selectedRepoId) {
			setMetrics(null);
			return;
		}

		async function loadMetrics() {
			try {
				setError(null);
				const data = await getDoraMetrics(selectedRepoId!, 30);
				setMetrics(data);
			} catch (err) {
				setError(err instanceof Error ? err.message : "Unable to load metrics");
			}
		}

		loadMetrics();
	}, [selectedRepoId]);

	useEffect(() => {
		if (!latestEvent) return;
		setReviews((current) => [latestEvent, ...current].slice(0, 25));
	}, [latestEvent]);

	const selectedRepo = useMemo(
		() => repos.find((repo) => String(repo.id) === selectedRepoId) ?? null,
		[repos, selectedRepoId],
	);

	const deploymentFrequency = getMetric(metrics, "deployment_frequency");
	const leadTime = getMetric(metrics, "lead_time_for_changes");
	const mttr = getMetric(metrics, "mean_time_to_restore");
	const changeFailureRate = getMetric(metrics, "change_failure_rate");

	async function handleLoadGithubRepos() {
		try {
			setLoadingGithubRepos(true);
			setError(null);
			const githubRepoList = await listGitHubRepos();
			setGithubRepos(githubRepoList);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Unable to load GitHub repositories");
		} finally {
			setLoadingGithubRepos(false);
		}
	}

	async function handleConnectGithubRepo(githubRepo: GitHubRepo) {
		const githubRepoId = githubRepo.github_repo_id ?? githubRepo.id;

		try {
			setConnectingRepoId(githubRepoId);
			setError(null);

			const connectedRepo = await connectRepo({
				github_repo_id: githubRepoId,
				full_name: githubRepo.full_name,
			});

			const connectedRepos = await listRepos();
			setRepos(connectedRepos);
			setSelectedRepoId(String(connectedRepo.id));
			setGithubRepos((current) =>
				current.filter((repo) => (repo.github_repo_id ?? repo.id) !== githubRepoId),
			);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Unable to connect repository");
		} finally {
			setConnectingRepoId(null);
		}
	}

	if (loading) {
		return (
			<div className="center-screen">
				<div className="spinner" aria-label="Loading dashboard" />
			</div>
		);
	}

	return (
		<main className="dashboard-layout">
			<aside className="sidebar" aria-label="Repository sidebar">
				<div className="sidebar-section">
					<p className="eyebrow">Signed in</p>
					<div className="user-pill">
						{user?.avatar_url && (
							<img src={user.avatar_url} alt="" />
						)}
						<span>{user?.name ?? user?.login ?? "DevPulse user"}</span>
					</div>
				</div>

				<div className="sidebar-section">
					<div className="sidebar-heading-row">
						<p className="eyebrow">Repositories</p>
						<button
							type="button"
							className="small-button"
							onClick={handleLoadGithubRepos}
							disabled={loadingGithubRepos}
						>
							{loadingGithubRepos ? "Loading" : "Add"}
						</button>
					</div>

					<div className="repo-list">
						{repos.length === 0 && (
							<p className="muted">No repositories connected yet. Click Add to fetch GitHub repos.</p>
						)}

						{repos.map((repo) => (
							<button
								key={repo.id}
								className={String(repo.id) === selectedRepoId ? "repo-button active" : "repo-button"}
								onClick={() => setSelectedRepoId(String(repo.id))}
							>
								<span className="repo-name">{repoLabel(repo)}</span>
								<span className="repo-meta">{repo.is_active ? "Connected" : "Inactive"}</span>
							</button>
						))}
					</div>

					{githubRepos.length > 0 && (
						<div className="github-repo-picker">
							<p className="eyebrow">GitHub repos</p>

							{githubRepos.map((repo) => {
								const githubRepoId = repo.github_repo_id ?? repo.id;
								const alreadyConnected = repos.some(
									(connectedRepo) => connectedRepo.github_repo_id === githubRepoId,
								);
								const hasAdmin = hasAdminPermission(repo);

								return (
									<div key={githubRepoId} className="github-repo-row">
										<div>
											<strong>{repo.full_name}</strong>
											<span className="muted">
												{alreadyConnected
													? "Connected"
													: !hasAdmin
														? "Admin may be required"
														: repo.private
															? "Private · Admin"
															: "Public · Admin"}
											</span>
										</div>

										<button
											type="button"
											className="small-button"
											disabled={alreadyConnected || connectingRepoId === githubRepoId}
											onClick={() => handleConnectGithubRepo(repo)}
										>
											{alreadyConnected
												? "Added"
												: connectingRepoId === githubRepoId
													? "Connecting"
													: "Connect"}
										</button>
									</div>
								);
							})}
						</div>
					)}
				</div>
			</aside>

			<section className="dashboard-main">
				<div className="section-heading">
					<div>
						<p className="eyebrow">DORA metrics</p>
						<h1>{selectedRepo ? repoLabel(selectedRepo) : "Dashboard"}</h1>
						<p className="muted">
							{selectedRepo
								? "Review engineering delivery metrics for the selected repository."
								: "Connect or select a repository to view metrics and review activity."}
						</p>
					</div>

					<div className={connected ? "live-pill online" : "live-pill"}>
						<span />
						{connected ? "Live feed connected" : "Connecting live feed"}
					</div>
				</div>

				{error && <div className="alert">{error}</div>}

				{!selectedRepo && (
					<div className="empty-state">
						<h2>No repository selected</h2>
						<p className="muted">Click Add in the sidebar, connect a GitHub repo, then select it to view DORA metrics.</p>
					</div>
				)}

				{selectedRepo && (
					<>
						<div className="metrics-grid">
							<DoraCard
								label="Deployment frequency"
								value={deploymentFrequency.value}
								unit={deploymentFrequency.unit}
								performance={deploymentFrequency.performance}
							/>
							<DoraCard
								label="Lead time for changes"
								value={leadTime.value}
								unit={leadTime.unit}
								performance={leadTime.performance}
							/>
							<DoraCard
								label="MTTR"
								value={mttr.value}
								unit={mttr.unit}
								performance={mttr.performance}
							/>
							<DoraCard
								label="Change failure rate"
								value={changeFailureRate.value}
								unit={changeFailureRate.unit}
								performance={changeFailureRate.performance}
							/>
						</div>

						<div className="panel">
							<div className="panel-header">
								<h2>Deployment frequency</h2>
								<span className="badge badge-blue">Last 30 days</span>
							</div>
							<DoraBarChart data={metrics?.deployment_history ?? []} />
						</div>

						<div className="panel">
							<div className="panel-header">
								<h2>Recent AI reviews</h2>
								<span className="muted">{reviews.length} total</span>
							</div>

							<div className="review-feed">
								{reviews.slice(0, 5).map((review, index) => (
									<ReviewFeedItem key={`${review.id}-${index}`} review={review} />
								))}

								{reviews.length === 0 && (
									<p className="muted">No reviews yet. Open a pull request to generate review activity.</p>
								)}
							</div>
						</div>
					</>
				)}
			</section>

			<aside className="review-panel" aria-label="Live review feed">
				<div className="panel-header">
					<h2>Live review feed</h2>
					<span className={connected ? "badge badge-green" : "badge badge-muted"}>
						{connected ? "Connected" : "Connecting"}
					</span>
				</div>

				<div className="review-feed">
					{reviews.length === 0 && (
						<p className="muted">No review events yet. New pull request activity will appear here.</p>
					)}

					{reviews.map((review, index) => (
						<ReviewFeedItem key={`${review.id}-${index}`} review={review} animate={index === 0} />
					))}
				</div>
			</aside>
		</main>
	);
}
