import { FormEvent, useState } from "react";
import { ApiError } from "../api/client";
import { ChatDataRow, sendChatMessage } from "../api/chat";
import ChatBubble from "../components/AIChat/ChatBubble";

type ChatMessage = {
	id: string;
	role: "user" | "assistant";
	text: string;
	data?: ChatDataRow[] | null;
};

const starterPrompts = [
	"How many pull requests exist?",
	"Show the latest pull requests.",
	"How many PRs were merged this week?",
	"Summarize recent review activity.",
];

function createId() {
	return typeof crypto !== "undefined" && "randomUUID" in crypto
		? crypto.randomUUID()
		: `${Date.now()}-${Math.random()}`;
}

function errorMessage(err: unknown) {
	if (err instanceof ApiError) {
		if (err.status === 401) return "You are not signed in.";
		if (err.status === 422) return "Chat request format is invalid.";
		if (err.status === 429) return "AI quota exceeded. Try again later or switch models.";
		if (err.status === 502 || err.status === 503) return "AI service unavailable. Check backend logs.";
		return err.message;
	}

	return err instanceof Error ? err.message : "Chat request failed.";
}

export default function ChatPage() {
	const [messages, setMessages] = useState<ChatMessage[]>([
		{
			id: "welcome",
			role: "assistant",
			text: "Ask questions about pull requests, reviews, repositories, and DORA metrics.",
		},
	]);

	const [input, setInput] = useState("");
	const [sessionId, setSessionId] = useState<string | undefined>();
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	async function submitQuestion(question: string) {
		const trimmed = question.trim();
		if (!trimmed || loading) return;

		setMessages((current) => [
			...current,
			{
				id: createId(),
				role: "user",
				text: trimmed,
			},
		]);

		setInput("");
		setLoading(true);
		setError(null);

		try {
			const response = await sendChatMessage(trimmed, sessionId);

			setSessionId(response.session_id ?? sessionId);

			setMessages((current) => [
				...current,
				{
					id: createId(),
					role: "assistant",
					text: response.answer,
					data: response.data ?? null,
				},
			]);
		} catch (err) {
			setError(errorMessage(err));
		} finally {
			setLoading(false);
		}
	}

	function handleSubmit(event: FormEvent) {
		event.preventDefault();
		submitQuestion(input);
	}

	return (
		<main className="chat-page">
			<section className="chat-shell" aria-labelledby="chat-title">
				<header className="chat-header">
					<p className="eyebrow">Engineering data</p>
					<h1 id="chat-title">Ask DevPulse</h1>
					<p className="muted">Query repositories, pull requests, reviews, and delivery metrics.</p>
				</header>

				<div className="prompt-row" aria-label="Suggested prompts">
					{starterPrompts.map((prompt) => (
						<button
							key={prompt}
							type="button"
							className="prompt-chip"
							onClick={() => submitQuestion(prompt)}
							disabled={loading}
						>
							{prompt}
						</button>
					))}
				</div>

				<div className="chat-messages">
					{messages.map((message) => (
						<ChatBubble
							key={message.id}
							role={message.role}
							text={message.text}
							data={message.data}
						/>
					))}

					{loading && (
						<div className="typing-indicator" aria-label="DevPulse is working">
							<span />
							<span />
							<span />
						</div>
					)}
				</div>

				{error && <div className="alert">{error}</div>}

				<form className="chat-input-row" onSubmit={handleSubmit}>
					<input
						value={input}
						onChange={(event) => setInput(event.target.value)}
						placeholder="Ask about PRs, reviews, or metrics"
						aria-label="Chat question"
					/>
					<button type="submit" disabled={loading || !input.trim()}>
						Send
					</button>
				</form>
			</section>
		</main>
	);
}
