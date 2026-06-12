export type ApiErrorPayload = {
  detail?: string;
  message?: string;
  error?: string;
};

export class ApiError extends Error {
  status: number;
  payload?: ApiErrorPayload;

  constructor(status: number, message: string, payload?: ApiErrorPayload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

type ApiOptions = RequestInit & {
  skipAuthRedirect?: boolean;
};

const API_PREFIX = "/api";

function buildUrl(path: string) {
  if (path.startsWith("http")) return path;
  if (path.startsWith("/api")) return path;
  if (path.startsWith("/")) return `${API_PREFIX}${path}`;
  return `${API_PREFIX}/${path}`;
}

export async function apiFetch<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { skipAuthRedirect, headers, ...requestOptions } = options;

  const response = await fetch(buildUrl(path), {
    credentials: "include",
    ...requestOptions,
    headers: {
      "Content-Type": "application/json",
      ...(headers ?? {}),
    },
  });

  if (response.status === 401 && !skipAuthRedirect) {
    window.location.href = "/login";
    throw new ApiError(401, "Unauthorized");
  }

  const contentType = response.headers.get("content-type");
  const isJson = contentType?.includes("application/json");

  if (!response.ok) {
    const payload = isJson ? await response.json().catch(() => undefined) : undefined;
    const fallbackMessage = `Request failed with status ${response.status}`;
    const message = payload?.detail ?? payload?.message ?? payload?.error ?? fallbackMessage;
    throw new ApiError(response.status, message, payload);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return isJson ? ((await response.json()) as T) : ((await response.text()) as T);
}

export function get<T>(path: string, options?: ApiOptions) {
  return apiFetch<T>(path, {
    method: "GET",
    ...(options ?? {}),
  });
}

export function post<T, Body = unknown>(path: string, body?: Body, options?: ApiOptions) {
  return apiFetch<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
    ...(options ?? {}),
  });
}
