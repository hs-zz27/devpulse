import { useEffect, useState } from "react";

export function useSSE<T>(url: string, enabled = true) {
	const [latestEvent, setLatestEvent] = useState<T | null>(null);
	const [connected, setConnected] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		if (!enabled) return;

		const source = new EventSource(url, {
			withCredentials: true,
		});

		source.onopen = () => {
			setConnected(true);
			setError(null);
		};

		source.onmessage = (event) => {
			if (!event.data) return;

			try {
				setLatestEvent(JSON.parse(event.data) as T);
			} catch {
				// Ignore malformed/heartbeat-like messages.
			}
		};

		source.onerror = () => {
			setConnected(false);
			setError("Live feed disconnected. Reconnecting...");
		};

		return () => {
			source.close();
			setConnected(false);
		};
	}, [enabled, url]);

	return { latestEvent, connected, error };
}
