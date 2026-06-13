import { post } from "./client";

export type ChatDataRow = Record<string, string | number | boolean | null>;

export type ChatResponse = {
	answer: string;
	sql?: string | null;
	data?: ChatDataRow[] | null;
	session_id?: string | null;
	warnings?: string[];
};

export function sendChatMessage(question: string, sessionId?: string) {
	return post<ChatResponse>("/chat/", {
		question,
		session_id: sessionId ?? null,
	});
}
