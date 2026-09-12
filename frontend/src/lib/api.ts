export class ApiError extends Error {}

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = "Request failed";
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      message = `${message} (${response.status})`;
    }
    throw new ApiError(message);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export function friendlyError(code: string): string {
  const messages: Record<string, string> = {
    INVALID_GOOGLE_CREDENTIAL: "Google sign-in could not be verified.",
    GOOGLE_AUTH_NOT_CONFIGURED: "Google sign-in is not configured yet.",
    GOOGLE_AUTH_DISABLED: "Google sign-in is disabled.",
    TOO_MANY_ATTEMPTS: "Too many attempts. Try again in a few minutes.",
  };
  return messages[code] ?? code;
}

export function initials(value?: string): string {
  return (value || "Loom User")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function formatDate(value?: string, compact = false): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return compact
    ? date.toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}
