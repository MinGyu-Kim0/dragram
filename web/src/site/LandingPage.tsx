import { MyRecords } from "../history/MySentencesPage";
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

/** 드래그 범위의 시작·끝 핸들(DESIGN §3 드래그 범위 표시) */
function Handle({ end = false }: { end?: boolean }) {
  return (
    <span className={end ? "handle handle-end" : "handle"} aria-hidden="true" />
  );
}

/** 사이드 패널 결과 화면을 본뜬 정적 예시. 직접 쓴 문장이고 API를 부르지 않는다. */
function PanelPreview() {
  return (
    <figure className="preview" aria-labelledby="preview-caption">
      <figcaption id="preview-caption" className="muted">
        사이드 패널 예시
      </figcaption>
      <div className="preview-panel">
        <div className="card preview-sentence">
          <p lang="ja" className="preview-ja">
            忙しく<mark className="hl hl-lime">ても</mark>、毎朝
            <Handle />
            本を読む
            <mark className="hl hl-sky">ようにしてい</mark>
            ます。
            <Handle end />
          </p>
          <hr />
          <p className="secondary">
            바빠도 매일 아침 책을 읽으려고 하고 있어요.
          </p>
        </div>
        <div className="preview-tabs" aria-hidden="true">
          <span className="active">문법 2</span>
          <span>단어 4</span>
        </div>
        <div className="card grammar-card selected">
          <div className="badge-row">
            <span className="badge-warn">AI 생성·미검수</span>
            <span className="muted">드래그한 부분</span>
          </div>
          <div className="grammar-title">
            <span lang="ja" className="chip chip-sky">
              ようにしている
            </span>
            <strong>~하도록 하고 있다</strong>
          </div>
          <p className="muted">
            문장 속 형태: <span lang="ja">ようにしてい</span>
          </p>
          <p className="secondary">
            습관이 되도록 꾸준히 신경 쓰고 있다는 뜻이에요.
          </p>
        </div>
        <div className="card grammar-card">
          <div className="grammar-title">
            <span lang="ja" className="chip chip-lime">
              ても
            </span>
            <strong>~해도</strong>
          </div>
          <p className="secondary">
            앞 내용과 상관없이 뒤의 일이 일어난다는 뜻이에요.
          </p>
        </div>
      </div>
    </figure>
  );
}

function Landing() {
  return (
    <>
      <section className="site-inner hero">
        <div className="hero-text">
          <h1>읽다가 막힌 일본어 문장, 드래그하면 문법이 보여요</h1>
          <p className="secondary">
            읽고 있는 일본어 문장을 드래그하면 번역과 함께 그 문장에 쓰인
            문법·단어를 바로 보여줘요.
          </p>
          <div className="hero-actions">
            <StoreButton />
            <a href="#how" className="secondary-button">
              작동 방식 보기
            </a>
          </div>
          <p className="muted">크롬 데스크톱에서 동작해요.</p>
        </div>
        <PanelPreview />
      </section>

      <section id="how" className="band" aria-labelledby="how-title">
        <div className="site-inner">
          <h2 id="how-title">세 단계면 돼요</h2>
          <ol className="steps" aria-label="시작하는 방법">
            {STEPS.map((step, i) => (
              <li key={step.title} className="card">
                <span className="step-number">{i + 1}</span>
                <h3>{step.title}</h3>
                <p className="secondary">{step.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section aria-labelledby="faq" className="site-inner faq">
        <h2 id="faq">자주 묻는 질문</h2>
        {FAQ.map((item) => (
          <details key={item.q}>
            <summary>{item.q}</summary>
            <p className="secondary">{item.a}</p>
          </details>
        ))}
      </section>
    </>
  );
}

/** /: 로그인했으면 홈, 아니면 소개 페이지. 홈 대시보드를 정하기 전까지 홈은 내 기록 목록이다. */
function HomePage() {
  return (
    <SiteLayout>{(user) => (user ? <MyRecords /> : <Landing />)}</SiteLayout>
  );
}

export default HomePage;
