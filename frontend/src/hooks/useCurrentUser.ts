import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { CurrentUser, getMe } from "../api/auth";

export function useCurrentUser() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadUser() {
      try {
        setLoading(true);
        setError(null);
        const currentUser = await getMe();
        if (active) setUser(currentUser);
      } catch (err) {
        if (!active) return;
        setUser(null);
        if (err instanceof ApiError && err.status === 401) {
          setError("Not authenticated");
        } else {
          setError(err instanceof Error ? err.message : "Unable to load user");
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    loadUser();

    return () => {
      active = false;
    };
  }, []);

  return { user, loading, error };
}
