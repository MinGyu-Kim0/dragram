import { API_BASE_URL, LoginRequired } from "./api";
import { clearTokenIfStill, loadToken } from "./auth";

// 지정한 이름(#136): 사용자가 단어 카드의 표기를 이름으로 지정한 것. 본인만 보는 개인 데이터라
// 표기는 URL이 아닌 본문으로 보낸다(접근 로그에 남지 않게).
export interface DesignatedName {
  // 원문 토큰의 표층형
  surface: string;
  // 히라가나 읽기. 없으면 null이다.
  reading: string | null;
}

// 서버가 받는 읽기: 가나만(장음 부호 포함). 서버도 같은 규칙으로 다시 본다.
const KANA = /^[ぁ-ゖゝゞァ-ヺー-ヾㇰ-ㇿ]+$/u;

export function isKana(text: string) {
  return KANA.test(text);
}

export function toHiragana(text: string) {
  return text.replace(/[ァ-ヶ]/gu, (c) =>
    String.fromCharCode(c.charCodeAt(0) - 0x60),
  );
}

// 로그인한 요청을 보낸다. 401이면 토큰을 지우고 LoginRequired, 그 밖의 실패는 오류다.
async function request(method: string, body?: object): Promise<Response> {
  const token = await loadToken();
  if (!token) throw new LoginRequired();
  const response = await fetch(`${API_BASE_URL}/api/names/`, {
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
  if (!response.ok) throw new Error("이름 요청 실패");
  return response;
}

export async function fetchNames(): Promise<DesignatedName[]> {
  const response = await request("GET");
  return ((await response.json()) as { names: DesignatedName[] }).names;
}

// 지정한다. 같은 표기면 읽기만 바뀐다. 빈 읽기는 읽기 없음이다.
export async function saveName(
  surface: string,
  reading: string,
): Promise<DesignatedName> {
  const response = await request("PUT", { surface, reading });
  return (await response.json()) as DesignatedName;
}

export async function removeName(surface: string): Promise<void> {
  await request("DELETE", { surface });
}
