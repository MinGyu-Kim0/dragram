import type { GrammarItem } from "@/utils/api";

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
export function HighlightedText({
  text,
  grammar,
}: {
  text: string;
  grammar: GrammarItem[];
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
        const segment = text.slice(start, end);
        const index = sorted.findIndex(
          (item) => item.start <= start && end <= item.end,
        );
        if (index === -1) return segment;
        return (
          <mark key={start} className={`highlight ${highlightClass(index)}`}>
            {segment}
          </mark>
        );
      })}
    </>
  );
}

export function GrammarCards({
  text,
  grammar,
}: {
  text: string;
  grammar: GrammarItem[];
}) {
  if (grammar.length === 0) {
    return <p className="no-grammar">문법 요소 없음</p>;
  }
  return (
    <ul className="grammar-cards" aria-label="문법">
      {sortGrammar(grammar).map((item, index) => (
        <li key={`${item.start}-${item.end}-${index}`} className="grammar-card">
          <div className="grammar-card-head">
            <span lang="ja" className={`grammar-chip ${highlightClass(index)}`}>
              {text.slice(item.start, item.end)}
            </span>
            <h3>{item.name}</h3>
            {item.review_status === "pending" && (
              <span className="badge-warn">AI 생성·미검수</span>
            )}
          </div>
          <p className="grammar-explanation">{item.explanation_ko}</p>
        </li>
      ))}
    </ul>
  );
}
