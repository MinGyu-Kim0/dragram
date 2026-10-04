import SentenceLibrary from "../features/library/SentenceLibrary";

function Home() {
  return (
    <main>
      <section className="hero">
        <span className="eyebrow">일본어를 문장 속에서 이해하기</span>
        <h1>읽은 문장을 바로 분석하고, 잊기 전에 다시 복습하세요.</h1>
        <p>확장 프로그램에서 분석한 문장과 어휘, 정규화된 문법이 이곳에 저장됩니다.</p>
      </section>
      <section className="cards" aria-label="주요 기능">
        <article><strong>문장 분석</strong><span>드래그한 문장을 어휘와 문법 단위로 확인합니다.</span></article>
        <article><strong>복습</strong><span>저장된 문장에 적용된 어휘와 문법을 다시 봅니다.</span></article>
      </section>
    </main>
  );
}

export default function App() {
  return (
    <div className="app-shell">
      <header>
        <a className="brand" href="/">DRAGRAM</a>
        <nav aria-label="주요 메뉴">
          <a href="#review">복습</a>
        </nav>
        <span className="mode">로컬 모드</span>
      </header>
      <Home />
      <SentenceLibrary />
    </div>
  );
}
