import { WEB_ORIGIN } from "@/utils/external-messages";

// 로그인 전(DESIGN 사이드 패널 '로그인 전'). 웹 '로그인·확장 연결' 화면에서 연결한다.
export function LoginPrompt() {
  return (
    <section className="login-prompt">
      <h2>로그인이 필요해요</h2>
      <p>
        문장을 분석하려면 웹에서 Google 계정으로 로그인하고 확장 프로그램을
        연결해 주세요.
      </p>
      <button
        type="button"
        className="primary-button"
        onClick={() => browser.tabs.create({ url: `${WEB_ORIGIN}/connect` })}
      >
        로그인하고 연결하기
      </button>
      <p className="muted">
        분석할 문장은 Dragram 서버로 보내 분석하고, 분석에는 OpenAI를 써요.
      </p>
    </section>
  );
}
