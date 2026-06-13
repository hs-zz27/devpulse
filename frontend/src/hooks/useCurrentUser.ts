import { useEffect, useState } from "react";
import { CurrentUser, getMe } from "../api/auth";
import { ApiError } from "../api/client";

export function useCurrentUser() {
	const [user, setUser] = useState<CurrentUser | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;

		async function loadUser() {
			try {
				setLoading(true);
				setError(null);

				const currentUser = await getMe();

				if (!cancelled) setUser(currentUser);
			} catch (err) {
				if (cancelled) return;

				if (err instanceof ApiError && err.status === 401) {
					setUser(null);
					setError(null);
				} else {
					setError(err instanceof Error ? err.message : "Unable to load current user");
				}
			} finally {
				if (!cancelled) setLoading(false);
			}
		}

		loadUser();

		return () => {
			cancelled = true;
		};
	}, []);

	return { user, loading, error };
}
