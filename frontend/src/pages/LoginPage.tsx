export default function LoginPage() {
	return (
		<main className="login-page">
			<section className="login-card" aria-labelledby="login-title">
				<div className="login-logo-row">
					<span className="logo-mark">DP</span>
					<span>DevPulse</span>
				</div>

				<p className="eyebrow">GitHub connected analytics</p>
				<h1 id="login-title">Sign in to DevPulse</h1>

				<p className="muted">
					Connect GitHub to view review activity, DORA metrics, repository health, and engineering insights.
				</p>

				<a className="github-button" href="/auth/login">
					Continue with GitHub
				</a>
			</section>
		</main>
	);
}
