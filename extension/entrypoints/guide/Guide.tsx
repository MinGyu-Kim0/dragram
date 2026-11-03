import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Logo } from "../sidepanel/Logo";
import { SentenceView } from "../sidepanel/Sentence";
import { ANALYSIS, ITEMS, TEXT, noop, nothing } from "./example";
import { STEPS } from "./steps";

// 가이드(#370): 실제 패널 컴포넌트로 그린 장면 위에서 한 단계씩 요소를 밝혀 설명한다.
// 강조할 자리는 장면 안 요소의 위치를 재서 정하므로, 창 크기·테마가 바뀌어도 맞는 곳을 가리킨다.
const PAD = 8;
const GAP = 72;
const BOX_WIDTH = 320;

interface Spot {
  top: number;
  left: number;
  width: number;
  height: number;
}

export function Guide() {
  const [index, setIndex] = useState(0);
  const [spot, setSpot] = useState<Spot>();
  const scene = useRef<HTMLDivElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const step = STEPS[index]!;
  const last = index === STEPS.length - 1;
  const next = () => setIndex((i) => Math.min(i + 1, STEPS.length - 1));
  const prev = () => setIndex((i) => Math.max(i - 1, 0));

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") next();
      else if (event.key === "ArrowLeft") prev();
      else if (event.key === "Escape") window.close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useLayoutEffect(() => {
    const target = scene.current?.querySelector(step.target);
    // 패널 스크롤 밖에 있으면 먼저 보이게 한다.
    target?.scrollIntoView?.({ block: "center" });
    const measure = () => {
      const rect = target?.getBoundingClientRect();
      setSpot(
        rect && {
          top: rect.top - PAD,
          left: rect.left - PAD,
          width: rect.width + PAD * 2,
          height: rect.height + PAD * 2,
        },
      );
    };
    measure();
    // 글꼴이 늦게 실리면 자리가 바뀌므로 한 번 더 잰다.
    const frame = requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    primary.current?.focus();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
    };
  }, [step]);

  return (
    <div className="guide">
      <Scene tab={step.tab ?? "grammar"} menu={!!step.menu} sceneRef={scene} />
      {spot && <div className="guide-spot" style={spot} aria-hidden="true" />}
      {spot && <Arrow spot={spot} />}
      <section
        className="guide-box"
        style={boxPosition(spot)}
        role="dialog"
        aria-modal="true"
        aria-labelledby="guide-title"
        aria-describedby="guide-body"
      >
        <p className="guide-progress">
          {index + 1} / {STEPS.length}
        </p>
        <h2 id="guide-title">{step.title}</h2>
        <p id="guide-body" aria-live="polite">
          {step.body}
        </p>
        <div className="guide-actions">
          <button
            type="button"
            className="text-button"
            onClick={() => window.close()}
          >
            건너뛰기
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={index === 0}
            onClick={prev}
          >
            이전
          </button>
          {last ? (
            <button
              ref={primary}
              type="button"
              className="primary-button"
              onClick={() => window.close()}
            >
              시작하기
            </button>
          ) : (
            <button
              ref={primary}
              type="button"
              className="primary-button"
              onClick={next}
            >
              다음
            </button>
          )}
        </div>
      </section>
    </div>
  );
}

// 강조한 자리가 화면 오른쪽이면 왼쪽에, 아니면 오른쪽에 설명 상자를 둔다.
function onLeft(spot: Spot) {
  return spot.left + spot.width / 2 > window.innerWidth / 2;
}

function boxPosition(spot: Spot | undefined) {
  if (!spot) return { top: 16, left: 16 };
  const left = onLeft(spot)
    ? Math.max(16, spot.left - GAP - BOX_WIDTH)
    : Math.min(
        window.innerWidth - BOX_WIDTH - 16,
        spot.left + spot.width + GAP,
      );
  const top = Math.min(
    Math.max(16, spot.top + spot.height / 2 - 80),
    window.innerHeight - 280,
  );
  return { top, left, width: BOX_WIDTH };
}

// 설명 상자에서 강조한 자리로 가는 화살표
function Arrow({ spot }: { spot: Spot }) {
  const box = boxPosition(spot);
  const left = onLeft(spot);
  const fromX = left ? box.left + BOX_WIDTH : box.left;
  const fromY = box.top + 56;
  const toX = left ? spot.left - 6 : spot.left + spot.width + 6;
  const toY = spot.top + spot.height / 2;
  const bend = (fromX + toX) / 2;
  return (
    <svg className="guide-arrow" aria-hidden="true">
      <defs>
        <marker
          id="guide-head"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="8"
          markerHeight="8"
          orient="auto-start-reverse"
        >
          <path d="M0 0L10 5L0 10z" />
        </marker>
      </defs>
      <path
        d={`M${fromX} ${fromY} C${bend} ${fromY} ${bend} ${toY} ${toX} ${toY}`}
        markerEnd="url(#guide-head)"
      />
    </svg>
  );
}

// 장면: 단순하게 그린 브라우저 창. 왼쪽은 예시 웹페이지, 오른쪽은 실제 패널 컴포넌트다.
// 그림이라 누를 수 없고(inert), 버튼은 아무것도 저장하지 않는다.
function Scene({
  tab,
  menu,
  sceneRef,
}: {
  tab: "grammar" | "words";
  menu: boolean;
  sceneRef: React.Ref<HTMLDivElement>;
}) {
  return (
    <div className="guide-scene" ref={sceneRef} inert>
      <div className="browser-tabs">
        <span className="browser-tab">雨の日の週末 | 日本語ブログ</span>
      </div>
      <div className="browser-bar">
        <span className="browser-address">blog.example.jp/rainy-weekend</span>
      </div>
      <div className="browser-body">
        <article className="fake-page" lang="ja">
          <h2>雨の日の週末</h2>
          <p>
            田中さんは毎週末、友だちと海へ行く。でも、今週は朝から天気が悪かった。
            <span className="fake-selection">{TEXT}</span>
            それで、家でゆっくり本を読んだ。
          </p>
          <p>
            来週は晴れるといいね、と田中さんは笑った。雨の日の静かな時間も、悪くないかもしれない。
          </p>
          {menu && (
            <ul className="fake-menu" lang="ko">
              <li>뒤로</li>
              <li>복사</li>
              <li>Google에서 검색</li>
              <li className="fake-menu-item" data-guide="menu-analyze">
                <img src="/icon/16.png" alt="" width="16" height="16" />
                Dragram으로 분석
              </li>
            </ul>
          )}
        </article>
        <aside className="fake-panel">
          <header className="panel-header">
            <Logo />
            <div className="header-actions">
              <span className="theme-button help-button">?</span>
            </div>
          </header>
          <SentenceView
            text={TEXT}
            showRuby
            onToggleRuby={noop}
            highlightStyle="marker"
            onHighlightStyleChange={noop}
            result={{ status: "done", analysis: ANALYSIS }}
            tab={tab}
            onTabChange={noop}
            onRetry={noop}
            names={new Map()}
            onSave={nothing}
            onRemove={nothing}
            items={ITEMS}
          />
        </aside>
      </div>
    </div>
  );
}
