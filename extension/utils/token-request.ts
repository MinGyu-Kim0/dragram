import { API_BASE_URL, LoginRequired } from "./api";
import { clearTokenIfStill, loadToken } from "./auth";

// 확장 토큰으로 로그인한 요청을 보낸다. 401이면 토큰을 지우고 LoginRequired, 그 밖의 실패는
// 오류다. 개인 데이터(표기, 예문)는 URL이 아닌 본문으로 보낸다(접근 로그에 남지 않게).
export async function tokenRequest(
  path: string,
  method: string,
  body?: object,
): Promise<Response> {
  const token = await loadToken();
  if (!token) throw new LoginRequired();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body && { "Content-Type": "application/json" }),
    },
    body: body && JSON.stringify(body),
  });
  if (response.status === 401) {
    await clearTokenIfStill(token);
    throw new LoginRequired();
  }
  if (!response.ok) throw new Error(`${method} ${path} 실패`);
  return response;
}
