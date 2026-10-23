// 확장 토큰(#109). 웹 '로그인·확장 연결' 화면이 넘겨준 토큰을 확장 저장소에 둔다.
// 분석 API는 이 토큰을 Bearer로 붙여 부른다.

const TOKEN_KEY = "extensionToken";
// 패널이 보던 원문·결과를 비우라는 표시. 명시적 로그아웃과 다른 계정의 연결 때 남긴다.
const SIGNED_OUT_KEY = "signedOutAt";

export async function loadToken(): Promise<string | undefined> {
  const stored = await browser.storage.local.get(TOKEN_KEY);
  const token = stored[TOKEN_KEY];
  return typeof token === "string" && token ? token : undefined;
}

// 토큰을 바꾸는 일은 백그라운드(웹의 connect·disconnect)와 사이드 패널(로그아웃, 401)에서
// 일어난다. 확인하고 지우는 사이에 다른 쪽이 새 토큰을 저장하지 않도록 한 줄로 세운다.
// 확장의 모든 맥락은 출처가 같아 Web Locks를 함께 쓴다. 없으면(테스트) 이 맥락 안에서만 세운다.
const TOKEN_LOCK = "dragram-extension-token";
let queue: Promise<unknown> = Promise.resolve();

function withTokenLock<T>(task: () => Promise<T>): Promise<T> {
  const locks = globalThis.navigator?.locks;
  if (locks) return locks.request(TOKEN_LOCK, task) as Promise<T>;
  const run = queue.then(task, task);
  queue = run.catch(() => undefined);
  return run;
}

// 연결한 계정 식별자(서버가 준 바뀌지 않는 값). 다른 계정이 연결하면 패널이 보던 원문·결과를
// 비운다.
const ACCOUNT_KEY = "extensionAccount";

// 웹에서 연결한 토큰을 저장한다. account가 지금 저장된 계정과 다르면(다른 사람일 수 있다)
// 비우라는 표시를 함께 남긴다. 같은 계정의 재연결은 기다리던 문장을 이어 분석한다.
export function saveToken(token: string, account?: string): Promise<void> {
  return withTokenLock(async () => {
    const stored = await browser.storage.local.get([TOKEN_KEY, ACCOUNT_KEY]);
    // 401로 토큰만 지워졌어도 계정은 남아 있어, 그 계정과 비교한다.
    const previous = stored[ACCOUNT_KEY];
    const replacesOther =
      account !== undefined &&
      (previous ? previous !== account : Boolean(stored[TOKEN_KEY]));
    await browser.storage.local.set({
      ...(replacesOther ? { [SIGNED_OUT_KEY]: Date.now() } : {}),
      [TOKEN_KEY]: token,
      ...(account !== undefined ? { [ACCOUNT_KEY]: account } : {}),
    });
  });
}

// 저장한 토큰이 token일 때만 지운다. 거부된 옛 토큰의 응답이 늦게 와도 그사이 다시 연결한
// 새 토큰을 지우지 않는다.
export function clearTokenIfStill(token: string): Promise<void> {
  return withTokenLock(async () => {
    if ((await loadToken()) === token)
      await browser.storage.local.remove(TOKEN_KEY);
  });
}

// 사용자가 명시적으로 로그아웃했다(패널 로그아웃, 웹 로그아웃). 401로 토큰을 지운 것과 달리
// 패널이 보던 원문·결과를 비워야 해서 표시를 남긴다. 표시와 토큰 지우기는 한 번에 저장한다.

const markSignedOut = () =>
  browser.storage.local.set({
    [SIGNED_OUT_KEY]: Date.now(),
    [TOKEN_KEY]: null,
    [ACCOUNT_KEY]: null,
  });

export function signOut(): Promise<void> {
  return withTokenLock(markSignedOut);
}

// 패널 로그아웃: 저장한 토큰이 token일 때만 로그아웃한다(그사이 다시 연결했으면 그대로 둔다).
export function signOutIfStill(token: string): Promise<void> {
  return withTokenLock(async () => {
    if ((await loadToken()) === token) await markSignedOut();
  });
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
