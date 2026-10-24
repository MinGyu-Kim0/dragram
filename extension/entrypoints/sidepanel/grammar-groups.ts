import type { GrammarItem } from "@/utils/api";

// 원문 순서로 정렬한다.
export function sortGrammar(grammar: GrammarItem[]): GrammarItem[] {
  return [...grammar].sort((a, b) => a.start - b.start || a.end - b.end);
}

// 원문 순서로 정렬한 문법 항목을 카드 묶음으로 나눈다(묶음 순서는 첫 자리의 원문 순서). 같은 용법으로
// 정해진 보통 카드는 한 묶음이 되어 카드 한 장과 색 번호 하나를 함께 쓴다. 해석 갈림·미확정은 따로다.
// 응답에 용법 ID가 없어 카드에 보이는 값이 모두 같으면 같은 용법으로 본다.
export function groupGrammar(grammar: GrammarItem[]): GrammarItem[][] {
  const groups = new Map<unknown, GrammarItem[]>();
  for (const item of sortGrammar(grammar)) {
    const key =
      item.state === "decided"
        ? JSON.stringify([
            item.name,
            item.explanation_ko,
            item.review_status,
            item.register,
            item.variant_of,
            (item.parts ?? []).map((part) => part.name),
          ])
        : item;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.values()];
}

// 화면에 보이는 문법 카드 수(합친 카드는 한 장, 구성 문법의 하위 박스도 센다)
export function grammarCardCount(grammar: GrammarItem[]): number {
  return groupGrammar(grammar).reduce(
    (count, [item]) => count + 1 + (item!.parts?.length ?? 0),
    0,
  );
}

// 응답에서 대안이 모두 빠진 해석 갈림은 보통 카드로 보인다.
export function isDivergent(item: GrammarItem): boolean {
  return (item.alternatives ?? []).length > 0;
}
