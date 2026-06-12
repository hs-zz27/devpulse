import { get } from "./client";

/**
 * Matches the User SQLAlchemy model in backend/app/models/user.py.
 * Fields: id (UUID), github_id, login, name, avatar_url, created_at.
 * Note: No "username" or "email" — the backend uses "login" for the GitHub handle.
 */
export type CurrentUser = {
  id: string;
  github_id: number;
  login: string;
  name?: string | null;
  avatar_url?: string | null;
  created_at: string;
};

export function getMe() {
  return get<CurrentUser>("/users/me", { skipAuthRedirect: true });
}
