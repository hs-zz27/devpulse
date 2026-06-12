import { post } from "./client";

export type ChatDataRow = Record<string, string | number | boolean | null>;

/**
 * Matches ChatResponse pydantic model in chat.py lines 240-245.
 */
export type ChatResponse = {
  answer: string;
  sql?: string | null;
  data?: ChatDataRow[] | null;
  session_id?: string | null;
  warnings?: string[];
};

/**
 * Matches ChatRequest pydantic model in chat.py lines 217-237.
 */
export function sendChatMessage(question: string, sessionId?: string) {
  return post<ChatResponse>("/chat/", {
    question,
    session_id: sessionId,
  });
}
