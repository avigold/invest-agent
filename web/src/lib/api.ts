const API_BASE = "";

export async function apiFetch(
  path: string,
  options?: RequestInit
): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  return res;
}

export async function apiJson<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await apiFetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : detail?.error ?? `API error: ${res.status}`;
    throw new Error(msg);
  }
  return res.json();
}
