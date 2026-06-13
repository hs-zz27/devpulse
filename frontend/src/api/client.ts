export class ApiError extends Error {
	status: number;
	detail: unknown;

	constructor(status: number, message: string, detail?: unknown) {
		super(message);
		this.name = "ApiError";
		this.status = status;
		this.detail = detail;
	}
}

type RequestOptions = Omit<RequestInit, "body"> & {
	body?: unknown;
};

function normalizeErrorMessage(payload: unknown, fallback: string) {
	if (!payload || typeof payload !== "object") return fallback;

	const detail = (payload as { detail?: unknown }).detail;

	if (typeof detail === "string") return detail;

	if (detail && typeof detail === "object") {
		const message = (detail as { message?: unknown }).message;
		if (typeof message === "string") return message;
	}

	return fallback;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
	const headers = new Headers(options.headers);

	if (options.body !== undefined && !headers.has("Content-Type")) {
		headers.set("Content-Type", "application/json");
	}

	const response = await fetch(`/api${path}`, {
		...options,
		headers,
		credentials: "include",
		body: options.body === undefined ? undefined : JSON.stringify(options.body),
	});

	const contentType = response.headers.get("Content-Type") ?? "";
	const hasJson = contentType.includes("application/json");
	const payload = hasJson ? await response.json().catch(() => null) : null;

	if (!response.ok) {
		if (response.status === 401) {
			throw new ApiError(401, "You are not signed in.", payload);
		}

		throw new ApiError(
			response.status,
			normalizeErrorMessage(payload, `Request failed with status ${response.status}`),
			payload,
		);
	}

	if (response.status === 204) return undefined as T;

	return payload as T;
}

export function get<T>(path: string) {
	return apiFetch<T>(path);
}

export function post<T>(path: string, body?: unknown) {
	return apiFetch<T>(path, {
		method: "POST",
		body,
	});
}

export function del<T>(path: string) {
	return apiFetch<T>(path, {
		method: "DELETE",
	});
}
