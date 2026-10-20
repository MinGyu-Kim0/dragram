import { Fragment, type ReactNode } from "react";
import type { GrammarItem, RubyItem } from "@/utils/api";
import { draggedFirst, type DragRange } from "./drag-range";

// 형광펜은 4색을 돌아가며 쓴다(DESIGN.md 형광펜). 원문 형광펜과 카드 칩이 같은 색이다.
const HIGHLIGHT_COLORS = 4;

function highlightClass(index: number): string {
  return `highlight-${index % HIGHLIGHT_COLORS}`;
}

// 원문 순서로 정렬한다. 색 번호도 이 순서로 매긴다.
function sortGrammar(grammar: GrammarItem[]): GrammarItem[] {
  return [...grammar].sort((a, b) => a.start - b.start || a.end - b.end);
}

// 원문에 문법 구간을 형광펜으로 칠한다. 구간이 겹치는 글자는 먼저 시작하는 문법의 색을 쓴다
// (겹침 표시 방식은 DESIGN.md 7장에서 아직 정하지 않았다).
// 실제로 드래그한 범위는 형광펜과 다른 층으로, 시작·끝 자리에 핸들만 끼워 넣는다(DESIGN.md).
// 핸들을 끄면 dragHandles가 undefined다. 루비는 형광펜 안에 단다(끄면 빈 목록).
// 형광펜을 범위 경계에서 쪼개면 조각마다 여백과 모서리가 생기므로 형광펜 안에 넣는다.
export function HighlightedText({
  text,
  grammar,
  ruby,
  dragHandles,
}: {
  text: string;
  grammar: GrammarItem[];
  ruby: RubyItem[];
  dragHandles: DragRange | undefined;
}) {
  const sorted = sortGrammar(grammar);
  const sortedRuby = [...ruby].sort((a, b) => a.start - b.start);
  const bounds = [
    ...new Set([
      0,
      text.length,
      ...sorted.flatMap((item) => [item.start, item.end]),
    ]),
  ].sort((a, b) => a - b);

  return (
    <>
      {bounds.slice(0, -1).map((start, i) => {
        const end = bounds[i + 1]!;
        const segment = withRuby(text, start, end, sortedRuby, dragHandles);
        const index = sorted.findIndex(
          (item) => item.start <= start && end <= item.end,
        );
        if (index === -1) return <Fragment key={start}>{segment}</Fragment>;
        return (
          <mark key={start} className={`highlight ${highlightClass(index)}`}>
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
// 칩 색은 카드 순서가 아니라 원문 순서로 매겨 형광펜과 맞춘다.
export function GrammarCards({
  text,
  grammar,
  selection,
}: {
  text: string;
  grammar: GrammarItem[];
  selection: DragRange;
}) {
  if (grammar.length === 0) {
    return <p className="no-grammar">문법 요소 없음</p>;
  }
  const ordered = draggedFirst(
    // 칩 색 번호는 원문 순서로 미리 매긴다.
    sortGrammar(grammar).map((item, index) => ({ ...item, index })),
    selection,
  );
  return (
    <ul className="grammar-cards" aria-label="문법">
      {ordered.map(({ item, dragged }) => (
        <li
          key={`${item.start}-${item.end}-${item.index}`}
          className={dragged ? "grammar-card dragged" : "grammar-card"}
        >
          <div className="grammar-card-head">
            <span
              lang="ja"
              className={`grammar-chip ${highlightClass(item.index)}`}
            >
              {text.slice(item.start, item.end)}
            </span>
            <h3>{item.name}</h3>
            {item.review_status === "pending" && (
              <span className="badge-warn">AI 생성·미검수</span>
            )}
            {dragged && <span className="drag-meta">드래그한 부분</span>}
          </div>
          <p className="grammar-explanation">{item.explanation_ko}</p>
        </li>
      ))}
    </ul>
  );
}
