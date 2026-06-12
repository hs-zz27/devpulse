import { useEffect, useState } from "react";

export type SSEState<T> = {
  latestEvent: T | null;
  connected: boolean;
  error: string | null;
};

export function useSSE<T = unknown>(url: string, enabled = true): SSEState<T> {
  const [latestEvent, setLatestEvent] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;

    const eventSource = new EventSource(url, { withCredentials: true });

    eventSource.onopen = () => {
      setConnected(true);
      setError(null);
    };

    eventSource.onmessage = (event) => {
      try {
        setLatestEvent(JSON.parse(event.data) as T);
      } catch {
        setLatestEvent(event.data as T);
      }
    };

    eventSource.onerror = () => {
      setConnected(false);
      setError("Live review stream disconnected");
    };

    return () => {
      eventSource.close();
    };
  }, [url, enabled]);

  return { latestEvent, connected, error };
}
