import { API_BASE_URL, LoginRequired, type PatternConnection } from "./api";
import { clearTokenIfStill, loadToken } from "./auth";

// 문장이나 원문 구간 없이 공용 패턴 ID만 보낸다. 서버는 저장된 값을 쓰거나 없는 것만 채운다.
export async function fetchConnection(
  patternId: number,
): Promise<PatternConnection> {
  const token = await loadToken();
  if (!token) throw new LoginRequired();
  const response = await fetch(
    `${API_BASE_URL}/api/grammar-patterns/${patternId}/connection/`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  if (response.status === 401) {
    await clearTokenIfStill(token);
    throw new LoginRequired();
  }
  if (!response.ok) throw new Error("접속 형태 요청 실패");
  const result = (await response.json()) as
    PatternConnection | { error: string };
  if ("error" in result) throw new Error("접속 형태 생성 실패");
  return result;
}
