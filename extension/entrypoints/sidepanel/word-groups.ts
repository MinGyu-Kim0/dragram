import type { NameSpan, WordItem } from "@/utils/api";
import { nameTypeLabel } from "./named-words";

// 원문 순서로 정렬한 단어를 행 묶음으로 나눈다(묶음 순서는 첫 자리의 원문 순서, #211). 문법 카드처럼
// 뜻이 정해진 단어는 위치를 뺀 내용(사전형·읽기·태그·뜻), 원문 표기, 이름 종류 배지가 모두 같으면
// 한 행이 된다. 합친 행은 첫 자리의 내용만 보이므로 하나라도 다르면 합치지 않는다. 표기가 다르면
// (食べた·食べる) 따로 두어, 표기 단위인 이름 지정을 행마다 할 수 있게 한다. 뜻을 아직 고르지 않은
// 자리와, 지정한 이름과 표기가 같은 자리(자리마다 이름 행·단어 카드 보기와 토글이 따로다)는 따로다.
export function groupWords(
  text: string,
  words: WordItem[],
  names: ReadonlyMap<string, string | null>,
  nameSpans: NameSpan[] | null | undefined,
): WordItem[][] {
  const groups = new Map<unknown, WordItem[]>();
  const sorted = [...words].sort((a, b) => a.start - b.start || a.end - b.end);
  for (const word of sorted) {
    const surface = text.slice(word.start, word.end);
    const key =
      word.sense !== null && !names.has(surface)
        ? JSON.stringify(
            [word, surface, nameTypeLabel(word, nameSpans)],
            (name, value) =>
              name === "start" || name === "end" ? undefined : value,
          )
        : word;
    groups.set(key, [...(groups.get(key) ?? []), word]);
  }
  return [...groups.values()];
}

// 화면에 보이는 단어 행 수(합친 행은 한 행)
export function wordRowCount(
  text: string,
  words: WordItem[],
  names: ReadonlyMap<string, string | null>,
  nameSpans: NameSpan[] | null | undefined,
): number {
  return groupWords(text, words, names, nameSpans).length;
}
