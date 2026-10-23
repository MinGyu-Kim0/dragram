// 웹 로그인 세션 API(같은 출처, Django 세션·CSRF). 개발 서버는 /api를 백엔드로 넘긴다.

export type User = { email: string };

export class AuthError extends Error {}

function csrfToken() {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith("csrftoken="))
    ?.slice("csrftoken=".length);
}

async function call(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<User | null> {
  const headers: Record<string, string> = {};
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    // 로그인하면 Django가 CSRF 값을 바꾸므로 요청마다 쿠키에서 다시 읽는다.
    headers["X-CSRFToken"] = csrfToken() ?? "";
  }
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok)
    throw new AuthError(`${method} ${path}: ${response.status}`);
  return ((await response.json()) as { user: User | null }).user;
}

/** 현재 로그인 사용자. 이 요청이 CSRF 쿠키도 받아 온다. */
export const currentUser = () => call("GET", "/api/auth/me/");

export const loginWithGoogle = (credential: string) =>
  call("POST", "/api/auth/google/", { credential });

export const logout = () => call("POST", "/api/auth/logout/");
