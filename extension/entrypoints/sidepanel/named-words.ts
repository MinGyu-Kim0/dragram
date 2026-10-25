import type { NameSpan, RubyItem, WordItem } from "@/utils/api";

// 단어 자리(원문 위치)의 키. '사전 단어 보기'로 바꾼 자리를 가른다.
export const wordKey = (word: WordItem) => `${word.start}-${word.end}`;

// 이름 행으로 보이는 단어와 그 읽기. 지정한 이름과 표층형이 같은 자리의 기본 보기는 공용 이름
// 구간(#140)이 고른다. 이름 구간이 없으면(null, 판단하기 전 분석) 이름 행, 있으면 그 안에 든 자리만
// 이름 행이다. flipped는 토글로 기본 보기와 반대로 바꾼 자리다.
export function namedWords(
  text: string,
  words: WordItem[],
  names: ReadonlyMap<string, string | null>,
  flipped: ReadonlySet<string>,
  nameSpans: NameSpan[] | null | undefined,
) {
  return words.flatMap((word) => {
    const surface = text.slice(word.start, word.end);
    if (!names.has(surface)) return [];
    const byDefault =
      nameSpans == null ||
      nameSpans.some(
        (span) => span.start <= word.start && word.end <= span.end,
      );
    return byDefault !== flipped.has(wordKey(word))
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
