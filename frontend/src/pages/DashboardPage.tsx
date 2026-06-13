import { useEffect, useMemo, useState } from "react";
import { CurrentUser, getMe } from "../api/auth";
import { DoraMetrics, getDoraMetrics, MetricValue } from "../api/metrics";
import {
	GitHubRepo,
	Repo,
	connectRepo,
	listGitHubRepos,
	listRepos,
	syncRepoPullRequests,
} from "../api/repos";
import { Review, getRecentReviews } from "../api/reviews";
import DoraBarChart from "../components/Charts/DoraBarChart";
import DoraCard from "../components/Dashboard/DoraCard";
import ReviewFeedItem from "../components/ReviewFeed/ReviewFeedItem";
import { useSSE } from "../hooks/useSSE";

function repoName(repo: Repo | GitHubRepo) {
	return repo.full_name;
}

function githubRepoId(repo: GitHubRepo) {
	return repo.github_repo_id ?? repo.id;
}

function hasAdminPermission(repo: GitHubRepo) {
	return Boolean(repo.permissions?.admin);
}

function normalizeMetric(
	metric: MetricValue | number | string | undefined,
	fallbackValue: number | string,
	fallbackUnit: string,
): MetricValue {
	if (metric && typeof metric === "object" && "value" in metric) {
		return {
			value: metric.value,
			unit: metric.unit ?? fallbackUnit,
			performance: metric.performance ?? "medium",
		};
	}

	return {
		value: metric ?? fallbackValue,
		unit: fallbackUnit,
		performance: "medium",
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
	const [syncingRepoId, setSyncingRepoId] = useState<string | null>(null);
	const [syncMessage, setSyncMessage] = useState<string | null>(null);

	const { latestEvent, connected } = useSSE<Review>("/api/reviews/stream", true);

	async function reloadRepos() {
		const connectedRepos = await listRepos();
		setRepos(connectedRepos);
		return connectedRepos;
	}

	async function reloadReviews() {
		const recentReviews = await getRecentReviews();
		setReviews(recentReviews);
		return recentReviews;
	}

	async function reloadMetrics(repoId: string) {
		const data = await getDoraMetrics(repoId, 30);
		setMetrics(data);
		return data;
	}

	async function handleSyncSelectedRepo() {
		if (!selectedRepoId) return;

		try {
			setSyncingRepoId(selectedRepoId);
			setSyncMessage(null);
			setError(null);

			const result = await syncRepoPullRequests(selectedRepoId);

			await Promise.all([
				reloadRepos(),
				reloadReviews(),
				reloadMetrics(selectedRepoId),
			]);

			setSyncMessage(
				`Synced ${result.fetched_count} pull requests (${result.inserted_count} new, ${result.updated_count} updated).`,
			);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Unable to sync pull requests");
		} finally {
			setSyncingRepoId(null);
		}
	}

	useEffect(() => {
		let cancelled = false;

		async function bootstrap() {
			try {
				setLoading(true);
				setError(null);

				const [currentUser, connectedRepos, recentReviews] = await Promise.all([
					getMe(),
					listRepos(),
					getRecentReviews(),
				]);

				if (cancelled) return;

				setUser(currentUser);
				setRepos(connectedRepos);
				setReviews(recentReviews);
				setSelectedRepoId(connectedRepos[0]?.id ? String(connectedRepos[0].id) : null);
			} catch (err) {
				if (!cancelled) {
					setError(err instanceof Error ? err.message : "Unable to load dashboard");
				}
			} finally {
				if (!cancelled) setLoading(false);
			}
		}

		bootstrap();

		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		if (!selectedRepoId) {
			setMetrics(null);
			return;
		}

		let cancelled = false;

		async function loadMetrics() {
			try {
				setError(null);

				const data = await getDoraMetrics(selectedRepoId as string, 30);

				if (!cancelled) setMetrics(data);
			} catch (err) {
				if (!cancelled) {
					setError(err instanceof Error ? err.message : "Unable to load metrics");
				}
			}
		}

		loadMetrics();

		return () => {
			cancelled = true;
		};
	}, [selectedRepoId]);

	useEffect(() => {
		if (!latestEvent) return;

		setReviews((current) => [latestEvent, ...current].slice(0, 25));
	}, [latestEvent]);

	const selectedRepo = useMemo(
		() => repos.find((repo) => String(repo.id) === selectedRepoId) ?? null,
		[repos, selectedRepoId],
	);

	const deploymentFrequency = normalizeMetric(
		metrics?.deployment_frequency ?? metrics?.deploymentFrequency,
		"—",
		"/day",
	);

	const leadTime = normalizeMetric(
		metrics?.lead_time_for_changes ?? metrics?.leadTimeForChanges,
		"—",
		"hrs",
	);

	const mttr = normalizeMetric(
		metrics?.mean_time_to_recovery ?? metrics?.mttr,
		"—",
		"hrs",
	);

	const changeFailureRate = normalizeMetric(
		metrics?.change_failure_rate ?? metrics?.changeFailureRate,
		"—",
		"%",
	);

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
		const id = githubRepoId(githubRepo);

		try {
			setConnectingRepoId(id);
			setError(null);
			setSyncMessage(null);

			const connectedRepo = await connectRepo({
				github_repo_id: id,
				full_name: githubRepo.full_name,
			});

			await reloadRepos();
			setSelectedRepoId(String(connectedRepo.id));
			setGithubRepos((current) => current.filter((repo) => githubRepoId(repo) !== id));

			await Promise.all([
				reloadReviews(),
				reloadMetrics(String(connectedRepo.id)),
			]);

			setSyncMessage("Repository connected and pull requests synced.");
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
						{(user?.avatar_url || user?.avatarUrl) && (
							<img src={user.avatar_url ?? user.avatarUrl} alt="" />
						)}
						<span>{user?.username ?? user?.login ?? user?.name ?? user?.email ?? "DevPulse user"}</span>
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
							<p className="muted">
								No repositories connected yet. Click Add to fetch GitHub repositories.
							</p>
						)}

						{repos.map((repo) => (
							<button
								key={repo.id}
								type="button"
								className={String(repo.id) === selectedRepoId ? "repo-button active" : "repo-button"}
								onClick={() => setSelectedRepoId(String(repo.id))}
							>
								<span className="repo-name">{repoName(repo)}</span>
								<span className="repo-meta">{repo.is_active ? "Connected" : "Inactive"}</span>
							</button>
						))}
					</div>

					{githubRepos.length > 0 && (
						<div className="github-repo-picker">
							<p className="eyebrow">GitHub repos</p>

							{githubRepos.map((repo) => {
								const id = githubRepoId(repo);
								const alreadyConnected = repos.some(
									(connectedRepo) => connectedRepo.github_repo_id === id,
								);
								const hasAdmin = hasAdminPermission(repo);

								return (
									<div key={id} className="github-repo-row">
										<div>
											<strong>{repo.full_name}</strong>
											<span className="muted">
												{alreadyConnected
													? "Connected"
													: hasAdmin
														? repo.private
															? "Private · Admin"
															: "Public · Admin"
														: "Admin may be required"}
											</span>
										</div>

										<button
											type="button"
											className="small-button"
											disabled={alreadyConnected || connectingRepoId === id}
											onClick={() => handleConnectGithubRepo(repo)}
										>
											{alreadyConnected
												? "Added"
												: connectingRepoId === id
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
						<h1>{selectedRepo ? repoName(selectedRepo) : "Dashboard"}</h1>
						<p className="muted">
							{selectedRepo
								? "Review engineering delivery metrics for the selected repository."
								: "Connect or select a repository to view metrics and review activity."}
						</p>
					</div>

					<div className="dashboard-actions">
						{selectedRepo && (
							<button
								type="button"
								className="button-secondary"
								onClick={handleSyncSelectedRepo}
								disabled={syncingRepoId === selectedRepoId}
							>
								{syncingRepoId === selectedRepoId ? "Syncing..." : "Sync now"}
							</button>
						)}

						<div className={connected ? "live-pill online" : "live-pill"}>
							<span />
							{connected ? "Live feed connected" : "Connecting live feed"}
						</div>
					</div>
				</div>

				{error && <div className="alert">{error}</div>}
				{syncMessage && <div className="notice">{syncMessage}</div>}

				{!selectedRepo && (
					<div className="empty-state">
						<h2>No repository selected</h2>
						<p className="muted">
							Click Add in the sidebar, connect a GitHub repository, then select it to view metrics.
						</p>
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

							<DoraBarChart data={metrics?.deployment_history ?? metrics?.deploymentHistory ?? []} />
						</div>

						<div className="panel">
							<div className="panel-header">
								<h2>Recent AI reviews</h2>
								<span className="muted">{reviews.length} total</span>
							</div>

							<div className="review-feed compact">
								{reviews.slice(0, 5).map((review, index) => (
									<ReviewFeedItem key={`${review.id}-${index}`} review={review} />
								))}

								{reviews.length === 0 && (
									<p className="muted">
										No reviews yet. Open a pull request to generate review activity.
									</p>
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
						<p className="muted">
							No review events yet. New pull request activity will appear here.
						</p>
					)}

					{reviews.map((review, index) => (
						<ReviewFeedItem key={`${review.id}-${index}`} review={review} animate={index === 0} />
					))}
				</div>
			</aside>
		</main>
	);
}
