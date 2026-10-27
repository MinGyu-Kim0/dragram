import { Link } from "react-router";
import SiteLayout from "./SiteLayout";

// 소개·설치(DESIGN WebLanding): 히어로 → 세 단계 카드 → FAQ.

const STEPS = [
  {
    title: "확장 프로그램 설치",
    text: "Chrome 웹 스토어에서 Dragram을 추가해요.",
  },
  {
    title: "로그인하고 연결",
    text: "Google 계정으로 로그인하고 확장 프로그램에 계정을 연결해요.",
  },
  {
    title: "문장을 드래그해 분석",
    text: "일본어 문장을 드래그하고 우클릭 메뉴의 'Dragram으로 분석'을 누르면 사이드 패널에 번역과 문법·단어가 나와요.",
  },
];

const FAQ = [
  {
    q: "어떤 글에서 쓸 수 있나요?",
    a: "Chrome에서 여는 일본어 웹페이지라면 어디서든 문장을 드래그해 분석할 수 있어요. 드래그한 부분은 앞뒤로 넓혀 온전한 문장으로 분석해요.",
  },
  {
    q: "드래그한 문장은 어디에 저장되나요?",
    a: "원문은 내 분석 기록으로만 저장되고 본인만 볼 수 있어요. 다른 사용자와 함께 쓰는 분석 결과에는 원문 대신 문장 해시와 번역, 문법·단어 정보만 남아요.",
  },
  {
    q: "'AI 생성·미검수'는 무슨 뜻인가요?",
    a: "AI가 만들었고 아직 관리자가 확인하지 않은 설명이나 뜻이에요. 틀릴 수 있으니 참고로만 봐 주세요.",
  },
  {
    q: "분석에 AI를 쓰나요?",
    a: "네. 번역과 문법 판정에 OpenAI를 써요. 자세한 내용은 개인정보처리방침에 있어요.",
  },
];

function StoreButton() {
  const url = import.meta.env.VITE_CHROME_WEB_STORE_URL;
  return url ? (
    <a className="primary-button" href={url}>
      Chrome에 추가
    </a>
  ) : (
    <span className="muted">Chrome 웹 스토어 준비 중</span>
  );
}

function LandingPage() {
  return (
    <SiteLayout>
      <section className="hero">
        <h1>
          Dragram
          <span className="hero-lead">
            내가 고른 일본어 글로 배우는 문법·단어
          </span>
        </h1>
        <p className="secondary">
          읽고 있는 일본어 문장을 드래그하면 번역과 함께 그 문장에 쓰인
          문법·단어를 바로 보여줘요.
        </p>
        <div className="hero-actions">
          <StoreButton />
          <Link to="/connect" className="secondary-button">
            로그인하고 연결하기
          </Link>
        </div>
      </section>

      <ol className="steps" aria-label="시작하는 방법">
        {STEPS.map((step, i) => (
          <li key={step.title} className="card">
            <span className="step-number">{i + 1}</span>
            <h2>{step.title}</h2>
            <p className="secondary">{step.text}</p>
          </li>
        ))}
      </ol>

      <section aria-labelledby="faq" className="faq">
        <h2 id="faq">자주 묻는 질문</h2>
        <dl>
          {FAQ.map((item) => (
            <div key={item.q}>
              <dt>{item.q}</dt>
              <dd className="secondary">{item.a}</dd>
            </div>
          ))}
        </dl>
      </section>
    </SiteLayout>
  );
}

export default LandingPage;
