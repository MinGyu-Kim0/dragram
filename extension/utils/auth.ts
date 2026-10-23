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

// 연결 상태(토큰이 있는지)를 지금 값과 이후 바뀔 때마다 알린다.
export function watchConnected(
  onChange: (connected: boolean) => void,
): () => void {
  const listener = (
    changes: Record<string, { newValue?: unknown }>,
    area: string,
  ) => {
    if (area === "local" && TOKEN_KEY in changes) {
      onChange(Boolean(changes[TOKEN_KEY]!.newValue));
    }
  };
  // 리스너를 먼저 달아야, 저장소를 읽는 사이에 바뀐 값을 놓치지 않는다.
  browser.storage.onChanged.addListener(listener);
  loadToken().then((token) => onChange(token !== undefined));
  return () => browser.storage.onChanged.removeListener(listener);
}
