import { Fragment, type ReactNode } from "react";
import type { GrammarItem } from "@/utils/api";
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
// 핸들을 끄면 dragHandles가 undefined다.
// 형광펜을 범위 경계에서 쪼개면 조각마다 여백과 모서리가 생기므로 형광펜 안에 넣는다.
export function HighlightedText({
  text,
  grammar,
  dragHandles,
}: {
  text: string;
  grammar: GrammarItem[];
  dragHandles: DragRange | undefined;
}) {
  const sorted = sortGrammar(grammar);
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
        const segment = dragHandles
          ? withHandles(text, start, end, dragHandles)
          : text.slice(start, end);
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

// 원문 [start, end) 글자에 드래그 핸들을 끼워 넣는다. 시작 핸들은 범위 첫 글자가 있는
// 조각에, 끝 핸들은 범위 마지막 글자가 있는 조각에 붙는다. 빈 범위에는 붙이지 않는다.
function withHandles(
  text: string,
  start: number,
  end: number,
  selection: DragRange,
): ReactNode[] {
  if (selection.start >= selection.end) return [text.slice(start, end)];
  const nodes: ReactNode[] = [];
  let at = start;
  if (start <= selection.start && selection.start < end) {
    nodes.push(text.slice(at, selection.start));
    nodes.push(
      <span key="start" aria-hidden="true" className="drag-handle-start" />,
    );
    at = selection.start;
  }
  if (start < selection.end && selection.end <= end) {
    nodes.push(text.slice(at, selection.end));
    nodes.push(
      <span key="end" aria-hidden="true" className="drag-handle-end" />,
    );
    at = selection.end;
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
