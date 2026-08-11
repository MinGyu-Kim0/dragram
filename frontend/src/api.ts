const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

export async function api<T>(path: string): Promise<T> {
  const response = await fetch(`${baseUrl}/api${path}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? "요청을 처리할 수 없습니다.");
  }
  return response.json();
}
