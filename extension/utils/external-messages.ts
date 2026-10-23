import { saveToken, signOut } from "./auth";

// 웹 '로그인·확장 연결' 화면의 출처. manifest externally_connectable에도 이 출처만 둔다.
// 바꾸려면 빌드할 때 WXT_WEB_ORIGIN을 준다.
// manifest처럼 출처로 정규화한다(끝 슬래시·경로를 떼어 낸다).
export const WEB_ORIGIN: string = new URL(
  import.meta.env.WXT_WEB_ORIGIN ?? "http://localhost:5173",
).origin;

export type ExternalReply = { ok: boolean };

function isFromWeb(url: string | undefined): boolean {
  if (!url) return false;
  try {
    return new URL(url).origin === WEB_ORIGIN;
  } catch {
    return false;
  }
}

// 웹이 chrome.runtime.sendMessage로 보낸 메시지를 처리한다.
// - {type: "connect", token, account}: 토큰과 연결한 계정 식별자를 저장한다(웹에서 연결).
//   account는 서버가 준 바뀌지 않는 값이다.
// - {type: "disconnect"}: 저장한 토큰을 지운다(웹 로그아웃).
// 우리 웹이 아닌 출처의 메시지는 답하지 않고 무시한다(undefined).
export function handleExternalMessage(
  message: unknown,
  senderUrl: string | undefined,
): Promise<ExternalReply> | undefined {
  if (!isFromWeb(senderUrl)) return undefined;
  const { type, token, account } = (message ?? {}) as {
    type?: unknown;
    token?: unknown;
    account?: unknown;
  };
  if (
    type === "connect" &&
    typeof token === "string" &&
    token &&
    typeof account === "string" &&
    account
  ) {
    return saveToken(token, account).then(() => ({ ok: true }));
  }
  if (type === "disconnect") {
    return signOut().then(() => ({ ok: true }));
  }
  return Promise.resolve({ ok: false });
}
