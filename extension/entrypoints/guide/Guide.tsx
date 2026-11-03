import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Logo } from "../sidepanel/Logo";
import { Pager } from "../sidepanel/Pager";
import { SentenceView, type ResultTab } from "../sidepanel/Sentence";
import { ANALYSIS, ITEMS, NEXT_TEXT, TEXT, noop, nothing } from "./example";
import { STEPS } from "./steps";

// 가이드(#370): 실제 패널 컴포넌트로 그린 장면 위에서 한 단계씩 요소를 밝혀 설명한다.
// 강조할 자리는 장면 안 요소의 위치를 재서 정하므로, 창 크기·테마가 바뀌어도 맞는 곳을 가리킨다.
// PAD: 밝힌 자리의 여백, GAP: 상자와 밝힌 자리 사이(화살표 자리), EDGE: 화면 가장자리 여백
const PAD = 8;
const GAP = 72;
const BOX_WIDTH = 320;
const EDGE = 16;

interface Spot {
  top: number;
  left: number;
  width: number;
  height: number;
}

export function Guide() {
  const [index, setIndex] = useState(0);
  const [spot, setSpot] = useState<Spot>();
  // 설명 상자의 실제 높이. 단계마다 글 길이가 달라 그린 뒤 잰다.
  const [boxHeight, setBoxHeight] = useState(0);
  const scene = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLElement>(null);
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
      setBoxHeight(box.current?.offsetHeight ?? 0);
    };
    measure();
    // 글꼴이 늦게 실리면 자리가 바뀌므로 다시 잰다.
    const frame = requestAnimationFrame(measure);
    void document.fonts?.ready.then(measure);
    window.addEventListener("resize", measure);
    primary.current?.focus();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
    };
  }, [step]);

  return (
    <div className="guide">
      <Scene
        tab={step.tab ?? "grammar"}
        menu={!!step.menu}
        selected={step.selected}
        sceneRef={scene}
      />
      {spot && <div className="guide-spot" style={spot} aria-hidden="true" />}
      {spot && <Arrow spot={spot} boxHeight={boxHeight} />}
      <section
        ref={box}
        className="guide-box"
        style={boxPosition(spot, boxHeight)}
        role="dialog"
        aria-modal="true"
        aria-labelledby="guide-title"
        aria-describedby="guide-body"
      >
        <p className="guide-progress">
          {index + 1} / {STEPS.length}
        </p>
        {/* 단계가 바뀌면 제목과 설명을 함께 읽는다. */}
        <div aria-live="polite">
          <h2 id="guide-title">{step.title}</h2>
          <p id="guide-body">{step.body}</p>
        </div>
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

// 상자는 밝힌 자리와 가운데 높이를 맞추되 화면 안에 둔다.
function boxPosition(spot: Spot | undefined, height: number) {
  if (!spot) return { top: EDGE, left: EDGE, width: BOX_WIDTH };
  const left = onLeft(spot)
    ? Math.max(EDGE, spot.left - GAP - BOX_WIDTH)
    : Math.min(
        window.innerWidth - BOX_WIDTH - EDGE,
        spot.left + spot.width + GAP,
      );
  const top = Math.max(
    EDGE,
    Math.min(
      spot.top + spot.height / 2 - height / 2,
      window.innerHeight - height - EDGE,
    ),
  );
  return { top, left, width: BOX_WIDTH };
}

// 설명 상자에서 강조한 자리로 가는 화살표
function Arrow({ spot, boxHeight }: { spot: Spot; boxHeight: number }) {
  const box = boxPosition(spot, boxHeight);
  const left = onLeft(spot);
  const fromX = left ? box.left + BOX_WIDTH : box.left;
  const fromY = box.top + boxHeight / 2;
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
  selected,
  sceneRef,
}: {
  tab: ResultTab;
  menu: boolean;
  selected: number | undefined;
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
            {/* 두 문장을 골라 패널이 문장별 페이지(1 / 2)로 나뉜 모습이다. */}
            <span className="fake-selection">
              {TEXT}
              {NEXT_TEXT}
            </span>
            {/* 우클릭 메뉴는 드래그를 끝낸 자리(선택 끝)에 붙인다. */}
            {menu && (
              <span className="fake-menu-anchor">
                <span className="fake-menu" lang="ko">
                  <span>뒤로</span>
                  <span>복사</span>
                  <span>Google에서 검색</span>
                  <span className="fake-menu-item" data-guide="menu-analyze">
                    <img src="/icon/16.png" alt="" width="16" height="16" />
                    Dragram으로 분석
                  </span>
                </span>
              </span>
            )}
          </p>
          <p>
            来週は晴れるといいね、と田中さんは笑った。雨の日の静かな時間も、悪くないかもしれない。
          </p>
        </article>
        <aside className="fake-panel">
          <header className="panel-header">
            <Logo />
            <div className="header-actions">
              <span className="theme-button guide-button">?</span>
            </div>
          </header>
          <Pager index={0} total={2} onGo={noop} />
          <SentenceView
            // 고른 글자는 처음 그릴 때만 받으므로 단계가 바꾸면 새로 그린다.
            key={selected ?? "none"}
            initialSelected={selected}
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
