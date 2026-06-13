import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useCurrentUser } from "./hooks/useCurrentUser";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import ChatPage from "./pages/ChatPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
	const { user, loading } = useCurrentUser();

	if (loading) {
		return (
			<div className="center-screen">
				<div className="spinner" aria-label="Loading" />
			</div>
		);
	}

	if (!user) return <Navigate to="/login" replace />;

	return <>{children}</>;
}

function ThemeToggle() {
	const [theme, setTheme] = useState<"light" | "dark">(() => {
		const stored = localStorage.getItem("devpulse-theme");
		if (stored === "dark" || stored === "light") return stored;
		return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
	});

	useEffect(() => {
		const root = document.documentElement;
		if (theme === "dark") {
			root.classList.add("dark");
		} else {
			root.classList.remove("dark");
		}
		localStorage.setItem("devpulse-theme", theme);
	}, [theme]);

	return (
		<button
			onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
			className="small-button"
			aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
		>
			{theme === "dark" ? "☀️ Day" : "🌙 Night"}
		</button>
	);
}

function AppShell({ children }: { children: React.ReactNode }) {
	return (
		<div className="app-shell">
			<header className="app-header">
				<NavLink to="/dashboard" className="brand" aria-label="DevPulse dashboard">
					<span className="brand-mark">DP</span>
					<span>DevPulse</span>
				</NavLink>

				<nav className="nav-links" aria-label="Primary navigation">
					<NavLink to="/dashboard">Dashboard</NavLink>
					<NavLink to="/chat">AI Chat</NavLink>
					<div style={{ paddingLeft: 8, marginLeft: 8, borderLeft: "1px solid var(--border)" }}>
						<ThemeToggle />
					</div>
				</nav>
			</header>

			{children}
		</div>
	);
}

export default function App() {
	return (
		<Routes>
			<Route path="/login" element={<LoginPage />} />
			<Route path="/" element={<Navigate to="/dashboard" replace />} />

			<Route
				path="/dashboard"
				element={
					<ProtectedRoute>
						<AppShell>
							<DashboardPage />
						</AppShell>
					</ProtectedRoute>
				}
			/>

			<Route
				path="/chat"
				element={
					<ProtectedRoute>
						<AppShell>
							<ChatPage />
						</AppShell>
					</ProtectedRoute>
				}
			/>

			<Route path="*" element={<Navigate to="/dashboard" replace />} />
		</Routes>
	);
}
