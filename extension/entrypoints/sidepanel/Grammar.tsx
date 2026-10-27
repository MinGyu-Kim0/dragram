import { Fragment, type ReactNode } from "react";
import type { CheckingItem, GrammarItem, RubyItem } from "@/utils/api";
import { BadgeRow } from "./BadgeRow";
import { ConnectionNote } from "./ConnectionNote";
import { draggedFirst, type DragRange } from "./drag-range";
import { groupGrammar, sortGrammar } from "./grammar-groups";
import { TAG_NAMES } from "./tag-names";

// 기능 태그 코드의 화면 이름(#151, 서버 FunctionTag와 같은 이름). 모르는 코드는 보이지 않는다.
const FUNCTION_TAG_NAMES: Record<string, string> = {
  passive: "수동",
  causative: "사역",
  causative_passive: "사역수동",
  potential: "가능",
  honorific: "존경",
  humble: "겸양",
  past: "과거",
  progressive: "진행",
  perfective: "완료",
  resultative: "결과 상태",
  polite: "정중",
  casual: "회화체",
  negative: "부정",
  conjecture: "추측",
  hearsay: "전문",
  obligation: "당위",
  conditional: "조건",
  cause: "원인·이유",
  adversative: "역접",
  purpose: "목적",
  listing: "나열",
  topic: "주제",
  subject: "주어",
  object: "목적어",
  target: "대상",
  place: "장소",
  time: "시간",
  means: "수단",
  goal: "도달점",
  source: "출발점",
  scope: "범위",
  comparison: "비교",
};

// 문법 카드 태그 줄: 품사 태그(원문 순서) → 기능 태그(서버가 준 허용 목록 순서)
function grammarTags(item: GrammarItem): string[] {
  return [
    ...item.pos_tags.map((code) => TAG_NAMES[code]),
    ...item.function_tags.map((code) => FUNCTION_TAG_NAMES[code]),
  ].filter((name): name is string => name !== undefined);
}

// 형광펜은 4색을 돌아가며 쓴다(DESIGN.md 형광펜). 원문 형광펜과 카드 칩이 같은 색이다.
const HIGHLIGHT_COLORS = 4;

function highlightClass(index: number): string {
  return `highlight-${index % HIGHLIGHT_COLORS}`;
}

// 원문에 문법 구간을 형광펜으로 칠한다. 구간이 겹치는 글자는 먼저 시작하는 문법의 색을 쓴다.
// 합친 카드의 자리는 모두 그 카드 색이다.
// 구성 문법(parts)은 받지 않으므로 그 글자는 바깥 카드 색이 된다(DESIGN.md 형광펜).
// 실제로 드래그한 범위는 형광펜과 다른 층으로, 시작·끝 자리에 핸들만 끼워 넣는다(DESIGN.md).
// 핸들을 끄면 dragHandles가 undefined다. 루비는 형광펜 안에 단다(끄면 빈 목록).
// 형광펜을 범위 경계에서 쪼개면 조각마다 여백과 모서리가 생기므로 형광펜 안에 넣는다.
// 판별 대상 구간(checking, 확인 중)은 형광펜 대신 점선 밑줄로 표시하고, 문법 구간과 겹치면 형광펜을
// 쓴다. 판별 대상 구간의 경계가 문법 구간 안에 있으면 형광펜이 쪼개지지 않게 그 경계는 쓰지 않는다.
export function HighlightedText({
  text,
  grammar,
  checking = [],
  ruby,
  dragHandles,
}: {
  text: string;
  grammar: GrammarItem[];
  checking?: CheckingItem[];
  ruby: RubyItem[];
  dragHandles: DragRange | undefined;
}) {
  const sorted = sortGrammar(grammar);
  const colors = new Map(
    groupGrammar(grammar).flatMap((group, color) =>
      group.map((item) => [item, color] as const),
    ),
  );
  const sortedRuby = [...ruby].sort((a, b) => a.start - b.start);
  const insideGrammar = (at: number) =>
    sorted.some((item) => item.start < at && at < item.end);
  const bounds = [
    ...new Set([
      0,
      text.length,
      ...sorted.flatMap((item) => [item.start, item.end]),
      ...checking
        .flatMap((item) => [item.start, item.end])
        .filter((at) => !insideGrammar(at)),
    ]),
  ].sort((a, b) => a - b);

  return (
    <>
      {bounds.slice(0, -1).map((start, i) => {
        const end = bounds[i + 1]!;
        const segment = withRuby(text, start, end, sortedRuby, dragHandles);
        const covers = (item: { start: number; end: number }) =>
          item.start <= start && end <= item.end;
        const index = sorted.findIndex(covers);
        if (index === -1) {
          const waiting = checking.some(covers);
          if (!waiting) return <Fragment key={start}>{segment}</Fragment>;
          return (
            <mark key={start} className="checking">
              {segment}
            </mark>
          );
        }
        return (
          <mark
            key={start}
            className={`highlight ${highlightClass(colors.get(sorted[index]!)!)}`}
          >
            {segment}
          </mark>
        );
      })}
    </>
  );
}

// 원문 [start, end)에 그 안에 다 들어가는 루비(원문 순서)를 단다. 나머지 글자에는 드래그 핸들을
// 제자리에 끼워 넣고, 핸들이 루비 단어 안에 걸리면 단어 바깥(시작은 앞, 끝은 뒤)에 붙인다.
function withRuby(
  text: string,
  start: number,
  end: number,
  ruby: RubyItem[],
  handles: DragRange | undefined,
): ReactNode[] {
  const nodes: ReactNode[] = [];
  let at = start;
  for (const piece of ruby) {
    if (piece.start < at || end < piece.end) continue;
    nodes.push(...withHandles(text, at, piece.start, handles));
    const [startHere, endHere] = handlesIn(piece.start, piece.end, handles);
    if (startHere) nodes.push(handleMark("start"));
    nodes.push(
      <ruby key={`ruby-${piece.start}`}>
        {text.slice(piece.start, piece.end)}
        <rt>{piece.reading}</rt>
      </ruby>,
    );
    if (endHere) nodes.push(handleMark("end"));
    at = piece.end;
  }
  nodes.push(...withHandles(text, at, end, handles));
  return nodes;
}

// 원문 [start, end)에 시작·끝 핸들이 들어가는가. 시작 핸들은 범위 첫 글자가 있는 곳에,
// 끝 핸들은 범위 마지막 글자가 있는 곳에 들어간다. 빈 범위에는 핸들이 없다.
function handlesIn(
  start: number,
  end: number,
  handles: DragRange | undefined,
): [boolean, boolean] {
  if (!handles || handles.start >= handles.end) return [false, false];
  return [
    start <= handles.start && handles.start < end,
    start < handles.end && handles.end <= end,
  ];
}

// 드래그 핸들 요소 하나(글자 없음)
function handleMark(kind: "start" | "end") {
  return (
    <span key={kind} aria-hidden="true" className={`drag-handle-${kind}`} />
  );
}

// 원문 [start, end) 글자의 핸들 자리에 핸들을 끼워 넣는다.
function withHandles(
  text: string,
  start: number,
  end: number,
  handles: DragRange | undefined,
): ReactNode[] {
  const [startHere, endHere] = handlesIn(start, end, handles);
  const nodes: ReactNode[] = [];
  let at = start;
  if (startHere) {
    nodes.push(text.slice(at, handles!.start), handleMark("start"));
    at = handles!.start;
  }
  if (endHere) {
    nodes.push(text.slice(at, handles!.end), handleMark("end"));
    at = handles!.end;
  }
  nodes.push(text.slice(at, end));
  return nodes.filter((node) => node !== "");
}

// 드래그 범위와 겹치는 카드를 먼저, 나머지를 그 뒤에 둔다. 각 묶음 안은 원문 순서이고,
// 칩 색은 카드 순서가 아니라 원문 순서로 매겨 형광펜과 맞춘다. 같은 용법 카드는 한 장으로 합치고
// (화면에서만), 그 자리 중 하나라도 드래그 범위와 겹치면 드래그한 카드다.
// 판별 대상 구간은 "확인 중" 점선 대기 카드로 원문 순서에 함께 넣는다(DESIGN.md).
export function GrammarCards({
  text,
  grammar,
  checking = [],
  selection,
}: {
  text: string;
  grammar: GrammarItem[];
  checking?: CheckingItem[];
  selection: DragRange;
}) {
  if (grammar.length === 0 && checking.length === 0) {
    return <p className="no-grammar">문법 요소 없음</p>;
  }
  const cards: Card[] = [
    // 칩 색 번호는 문법 카드끼리 원문 순서로 미리 매긴다.
    ...groupGrammar(grammar).map((items, index): Card => ({
      kind: "grammar",
      item: items[0]!,
      index,
      ...span(items[0]!),
      spans: items,
    })),
    ...checking.map((item, index): Card => ({
      kind: "checking",
      item,
      index,
      ...span(item),
    })),
  ].sort((a, b) => a.start - b.start || a.end - b.end);
  return (
    <ul className="grammar-cards" aria-label="문법">
      {draggedFirst(cards, selection).map(({ item: card, dragged }) =>
        card.kind === "checking" ? (
          <CheckingCard
            key={`checking-${card.index}`}
            text={text}
            item={card.item}
            dragged={dragged}
          />
        ) : (
          <GrammarCard
            key={`grammar-${card.index}`}
            text={text}
            item={card.item}
            index={card.index}
            dragged={dragged}
          />
        ),
      )}
    </ul>
  );
}

// 문법 카드 목록의 한 장. index는 같은 종류 안의 원문 순서다(문법 카드는 칩 색 번호로 쓴다).
type Card = { start: number; end: number; index: number } & (
  | { kind: "grammar"; item: GrammarItem; spans: GrammarItem[] }
  | { kind: "checking"; item: CheckingItem }
);

function span(item: { start: number; end: number }) {
  return { start: item.start, end: item.end };
}

// 구성 문법(parts)은 카드 안 하위 박스로 넣는다. 하위 박스는 색 번호를 따로 받지 않고 바깥 카드
// 색을 쓰며, 선택 링과 "드래그한 부분"은 바깥 카드에만 둔다(DESIGN.md 3장). 합친 카드는 첫 자리의
// 칩 글자와 구성 문법을 보인다.
function GrammarCard({
  text,
  item,
  index,
  dragged,
}: {
  text: string;
  item: GrammarItem;
  index: number;
  dragged: boolean;
}) {
  const classes = [
    "grammar-card",
    isDivergent(item) && "divergent",
    dragged && "dragged",
  ].filter(Boolean);
  const parts = item.parts ?? [];
  return (
    <li className={classes.join(" ")}>
      <GrammarBody
        text={text}
        item={item}
        index={index}
        Heading="h3"
        dragged={dragged}
      />
      {parts.length > 0 && (
        <ul className="grammar-parts" aria-label="구성 문법">
          {parts.map((part, i) => (
            <li
              key={i}
              className={
                isDivergent(part) ? "grammar-part divergent" : "grammar-part"
              }
            >
              <GrammarBody text={text} item={part} index={index} Heading="h4" />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

// 응답에서 대안이 모두 빠진 해석 갈림은 보통 카드로 보인다.
function isDivergent(item: GrammarItem): boolean {
  return (item.alternatives ?? []).length > 0;
}

// 문법 카드와 하위 박스가 함께 쓰는 내용: 배지 줄, 칩·이름, 태그(있을 때만), 대응 표현(있을
// 때만), 원형 안내, 설명이나 "판단하지 못함", 다른 해석. checking이면 판정 전이라 칩을 형광펜
// 색 대신 확인 중 칩으로 두고 제목 줄에 '확인 중'을 단다(#203).
function GrammarBody({
  text,
  item,
  index,
  Heading,
  dragged = false,
  checking = false,
}: {
  text: string;
  item: GrammarItem;
  index: number;
  Heading: "h3" | "h4";
  dragged?: boolean;
  checking?: boolean;
}) {
  const alternatives = item.alternatives ?? [];
  const tags = grammarTags(item);
  const surface = text.slice(item.start, item.end);
  return (
    <>
      <BadgeRow
        pending={item.review_status === "pending"}
        colloquial={item.register === "colloquial"}
        dragged={dragged}
      />
      <div className="grammar-card-head">
        <span
          lang="ja"
          className={`grammar-chip ${checking ? "checking-chip" : highlightClass(index)}`}
        >
          {item.pattern_name}
        </span>
        <Heading>{item.name}</Heading>
        {checking && <span className="card-meta">확인 중</span>}
      </div>
      {surface !== item.pattern_name && (
        <p className="grammar-form">
          문장 속 형태: <span lang="ja">{surface}</span>
        </p>
      )}
      <ConnectionNote
        connection={item.connection}
        pending={item.review_status === "pending"}
      />
      {tags.length > 0 && (
        <div className="grammar-tags">
          <ul className="word-tags" aria-label="태그">
            {tags.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
          {/* 미검수 용법이면 배지 줄의 배지 하나로 함께 보이고, 승인된 용법에 나중에 채운
              미검수 기능 태그만 이 줄에 배지 하나를 단다(#151, 태그마다 달지 않는다). */}
          {item.review_status === "approved" &&
            item.function_tags_review_status === "pending" && <PendingBadge />}
        </div>
      )}
      {item.korean_equivalent !== null && (
        <p className="korean-equivalent">
          {item.korean_equivalent}
          {/* 미검수 용법이면 배지 줄의 배지 하나로 함께 보이고, 승인된 용법에 나중에 채운
              미검수 대응 표현만 이 줄에 배지를 단다(#152). */}
          {item.review_status === "approved" &&
            item.korean_equivalent_review_status === "pending" && (
              <PendingBadge />
            )}
        </p>
      )}
      {item.variant_of !== null && (
        <p className="variant-note">「{item.variant_of}」의 회화체</p>
      )}
      {item.state === "unresolved" ? (
        <p className="grammar-explanation unresolved-note">판단하지 못함</p>
      ) : (
        <p className="grammar-explanation">{item.explanation_ko}</p>
      )}
      {alternatives.length > 0 && (
        <ul className="alternatives" aria-label="다른 해석">
          {alternatives.map((alternative) => (
            <li key={alternative.name} className="alternative">
              <span>
                다른 해석: {alternative.name} — {alternative.translation_ko}
              </span>
              {alternative.review_status === "pending" && <PendingBadge />}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function PendingBadge() {
  return <span className="badge-warn">AI 생성·미검수</span>;
}

// 판별 대상 구간(확인 중). 후보가 하나면 그 용법 내용을 채운 카드에 '확인 중'만 단다(#203).
// 여럿이면 아직 용법을 고르지 않아 후보 이름만 잇는다. 후보 이름도 LLM이 만든 지식이라 미검수
// 후보가 하나라도 있으면 'AI 생성·미검수' 배지를 단다(PR #61 리뷰).
function CheckingCard({
  text,
  item,
  dragged,
}: {
  text: string;
  item: CheckingItem;
  dragged: boolean;
}) {
  const className = dragged
    ? "grammar-card checking dragged"
    : "grammar-card checking";
  const surface = text.slice(item.start, item.end);
  if (item.usage) {
    return (
      <li className={className}>
        <GrammarBody
          text={text}
          item={{
            ...item.usage,
            start: item.start,
            end: item.end,
            state: "decided",
          }}
          index={0}
          Heading="h3"
          dragged={dragged}
          checking
        />
      </li>
    );
  }
  return (
    <li className={className}>
      <BadgeRow
        pending={item.candidates.some(
          (candidate) => candidate.review_status === "pending",
        )}
        dragged={dragged}
      />
      <div className="grammar-card-head">
        <span lang="ja" className="grammar-chip checking-chip">
          {item.pattern_name}
        </span>
        <h3>
          {item.candidates.map((candidate) => candidate.name).join(" · ")}
        </h3>
        <span className="card-meta">확인 중</span>
      </div>
      {surface !== item.pattern_name && (
        <p className="grammar-form">
          문장 속 형태: <span lang="ja">{surface}</span>
        </p>
      )}
      <ConnectionNote
        connection={item.connection}
        pending={item.candidates.some(
          (candidate) => candidate.review_status === "pending",
        )}
      />
      {/* 설명 자리 표시. 상태는 위 '확인 중' 글자로 읽힌다. */}
      <div aria-hidden="true" className="skeleton checking-skeleton">
        <span />
      </div>
    </li>
  );
}
