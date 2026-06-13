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
