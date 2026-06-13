import { get } from "./client";

export type CurrentUser = {
	id?: string;
	url?: string;
	email?: string;
	name?: string;
	username?: string;
	login?: string;
	avatar_url?: string;
	avatarUrl?: string;
};

export function getMe() {
	return get<CurrentUser>("/users/me");
}
