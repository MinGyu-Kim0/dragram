// 웹 → 확장 메시지(#109). 확장 manifest의 externally_connectable에 이 웹 출처가 있어야
// chrome.runtime.sendMessage로 보낼 수 있다. 확장 ID는 VITE_EXTENSION_ID로 받는다.

export type ExtensionMessage =
  // account: 연결한 계정 식별자(서버가 준 바뀌지 않는 값). 확장은 다른 계정이 연결하면
  // 패널이 보던 결과를 비운다.
  { type: "connect"; token: string; account: string } | { type: "disconnect" };

type Runtime = {
  lastError?: { message?: string };
  sendMessage(
    extensionId: string,
    message: ExtensionMessage,
    callback: (response?: { ok?: boolean }) => void,
  ): void;
};

declare global {
  interface Window {
    chrome?: { runtime?: Runtime };
  }
}

// 확장이 이 시간 안에 답하지 않으면 없는 것으로 본다.
const REPLY_TIMEOUT_MS = 3000;

/** 확장에 메시지를 보내고, 확장이 받았다고 답하면 true다. 확장이 없거나 답이 없으면 false다. */
export function sendToExtension(message: ExtensionMessage): Promise<boolean> {
  const extensionId = import.meta.env.VITE_EXTENSION_ID;
  const runtime = window.chrome?.runtime;
  if (!extensionId || !runtime?.sendMessage) return Promise.resolve(false);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), REPLY_TIMEOUT_MS);
    try {
      runtime.sendMessage(extensionId, message, (response) => {
        clearTimeout(timer);
        // 확장이 없으면 lastError가 생긴다. 읽어 두어야 크롬이 콘솔 오류를 남기지 않는다.
        resolve(!runtime.lastError && response?.ok === true);
      });
    } catch {
      // 확장 ID가 잘못되면 sendMessage가 바로 예외를 낸다.
      clearTimeout(timer);
      resolve(false);
    }
  });
}
