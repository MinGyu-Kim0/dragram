// 확장 토큰(#109). 웹 '로그인·확장 연결' 화면이 넘겨준 토큰을 확장 저장소에 둔다.
// 분석 API는 이 토큰을 Bearer로 붙여 부른다.

const TOKEN_KEY = "extensionToken";

export async function loadToken(): Promise<string | undefined> {
  const stored = await browser.storage.local.get(TOKEN_KEY);
  const token = stored[TOKEN_KEY];
  return typeof token === "string" && token ? token : undefined;
}

export async function saveToken(token: string): Promise<void> {
  await browser.storage.local.set({ [TOKEN_KEY]: token });
}

export async function clearToken(): Promise<void> {
  await browser.storage.local.remove(TOKEN_KEY);
}

// 저장한 토큰이 token일 때만 지운다. 거부된 옛 토큰의 응답이 늦게 와도 그사이 다시 연결한
// 새 토큰을 지우지 않는다.
export async function clearTokenIfStill(token: string): Promise<void> {
  if ((await loadToken()) === token) await clearToken();
}

// 사용자가 명시적으로 로그아웃했다(패널 로그아웃, 웹 로그아웃). 401로 토큰을 지운 것과 달리
// 패널이 보던 원문·결과를 비워야 해서 따로 알린다.
const SIGNED_OUT_KEY = "signedOutAt";

export async function signOut(): Promise<void> {
  await browser.storage.local.set({ [SIGNED_OUT_KEY]: Date.now() });
  await clearToken();
}

// 연결 상태(토큰이 있는지)를 지금 값과 이후 바뀔 때마다 알린다. 명시적으로 로그아웃하면
// onSignedOut으로 화면을 비우라고 알린다. 다시 연결해 토큰이 바뀌는 것은 로그아웃이 아니다
// (만료된 토큰을 같은 사람이 다시 연결할 때 기다리던 문장을 이어 분석한다).
export function watchConnection(handlers: {
  onConnected: (connected: boolean) => void;
  onSignedOut: () => void;
}): () => void {
  // 변경 알림을 받은 뒤에 끝난 처음 읽기는 오래된 값이라 버린다.
  let changed = false;
  const listener = (
    changes: Record<string, { newValue?: unknown }>,
    area: string,
  ) => {
    if (area !== "local") return;
    if (SIGNED_OUT_KEY in changes) handlers.onSignedOut();
    if (TOKEN_KEY in changes) {
      changed = true;
      handlers.onConnected(Boolean(changes[TOKEN_KEY]!.newValue));
    }
  };
  // 리스너를 먼저 달아야, 저장소를 읽는 사이에 바뀐 값을 놓치지 않는다.
  browser.storage.onChanged.addListener(listener);
  loadToken().then((token) => {
    if (!changed) handlers.onConnected(token !== undefined);
  });
  return () => browser.storage.onChanged.removeListener(listener);
}
