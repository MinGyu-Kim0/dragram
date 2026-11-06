import { useState } from "react";

// 서버가 이 확장 버전을 더는 받지 않는다(#349). Chrome에 업데이트 확인을 요청하고, 받을 업데이트가
// 있으면 확장을 다시 띄워 적용한다. 없거나 확인이 제한되면(throttled) 잠시 뒤 다시 하라고 한다.
export function UpdatePrompt() {
  const [notReady, setNotReady] = useState(false);
  const update = async () => {
    try {
      const { status } = await browser.runtime.requestUpdateCheck();
      if (status === "update_available") {
        browser.runtime.reload();
        return;
      }
    } catch {
      // 확인하지 못한 것도 받을 업데이트가 없는 것과 같이 안내한다.
    }
    setNotReady(true);
  };
  return (
    <section className="login-prompt">
      <h2>업데이트가 필요해요</h2>
      <p>
        이 버전의 확장 프로그램으로는 더 분석할 수 없어요. 확장 프로그램을
        업데이트해 주세요.
      </p>
      <button type="button" className="primary-button" onClick={update}>
        지금 업데이트
      </button>
      {notReady && (
        <p className="error" role="alert">
          아직 받을 수 있는 업데이트가 없어요. 잠시 뒤 다시 해 주세요.
        </p>
      )}
    </section>
  );
}
