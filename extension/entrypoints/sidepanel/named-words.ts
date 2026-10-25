import type { RubyItem, WordItem } from "@/utils/api";

// 단어 자리(원문 위치)의 키. '사전 단어 보기'로 바꾼 자리를 가른다.
export const wordKey = (word: WordItem) => `${word.start}-${word.end}`;

// 이름 행으로 보이는 단어(지정한 이름과 표층형이 같고 '사전 단어 보기'로 바꾸지 않은 자리)와 그
// 읽기
export function namedWords(
  text: string,
  words: WordItem[],
  names: ReadonlyMap<string, string | null>,
  asWord: ReadonlySet<string>,
) {
  return words.flatMap((word) => {
    const surface = text.slice(word.start, word.end);
    return names.has(surface) && !asWord.has(wordKey(word))
      ? [{ word, reading: names.get(surface)! }]
      : [];
  });
}

// 원문 루비. 읽기가 있는 이름 행 자리는 SudachiPy 루비 대신 지정한 읽기를 그 자리 전체에 단다.
export function withNameRuby(
  ruby: RubyItem[],
  named: { word: WordItem; reading: string | null }[],
): RubyItem[] {
  const replaced = named.filter(({ reading }) => reading);
  const kept = ruby.filter(
    (piece) =>
      !replaced.some(
        ({ word }) => piece.start < word.end && word.start < piece.end,
      ),
  );
  return [
    ...kept,
    ...replaced.map(({ word, reading }) => ({
      start: word.start,
      end: word.end,
      reading: reading!,
    })),
  ];
}
