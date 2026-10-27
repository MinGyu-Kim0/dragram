// 웹 로그인 세션 API(같은 출처, Django 세션·CSRF). 개발 서버는 /api를 백엔드로 넘긴다.

export type User = { email: string };

export class AuthError extends Error {}

function csrfToken() {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith("csrftoken="))
    ?.slice("csrftoken=".length);
}

async function request<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
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
  return (await response.json()) as T;
}

const userOf = (body: { user: User | null }) => body.user;

/** 현재 로그인 사용자. 이 요청이 CSRF 쿠키도 받아 온다. */
export const currentUser = () =>
  request<{ user: User | null }>("GET", "/api/auth/me/").then(userOf);

export const loginWithGoogle = (credential: string) =>
  request<{ user: User | null }>("POST", "/api/auth/google/", {
    credential,
  }).then(userOf);

/** 로그아웃. 서버는 이 세션이 발급한 확장 토큰도 폐기한다. */
export const logout = () =>
  request<{ user: User | null }>("POST", "/api/auth/logout/").then(userOf);

/** 회원 탈퇴. 서버는 계정과 원문 기록·지정한 이름·확장 연결·사용량 기록을 지운다. */
export const withdraw = () =>
  request<{ user: User | null }>("POST", "/api/auth/withdraw/").then(userOf);

/** 확장에 넘길 토큰을 발급받는다. 원본은 이 응답에만 있다. */
// account는 바뀌지 않는 계정 식별자다. 확장이 다른 계정의 연결인지 가릴 때 쓴다.
export const issueExtensionToken = () =>
  request<{ token: string; account: string }>(
    "POST",
    "/api/auth/extension-tokens/",
  );
