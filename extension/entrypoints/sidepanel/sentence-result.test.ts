import { describe, expect, test } from "vitest";
import type {
  Analysis,
  CheckingItem,
  GrammarItem,
  Translation,
  WordItem,
} from "@/utils/api";
import {
  analysisOf,
  checkingOf,
  earlyWordsOf,
  grammarOf,
  refusalOf,
  translationOf,
  type SentenceResult,
} from "./sentence-result";

const grammar = (name: string) => ({ name }) as unknown as GrammarItem;
const checking = (start: number) => ({ start }) as unknown as CheckingItem;
const word = (form: string) =>
  ({ dictionary_form: form }) as unknown as WordItem;
const translation = (text: string) =>
  ({ translation_ko: text }) as unknown as Translation;
const analysis = (text: string, name: string) =>
  ({
    translation_ko: text,
    grammar: [grammar(name)],
    words: [],
  }) as unknown as Analysis;

const OLD = analysis("옛 번역", "옛 문법");
const NEW = analysis("새 번역", "새 문법");

describe("지금 보일 분석", () => {
  test("끝났으면 그 결과다", () => {
    expect(analysisOf({ status: "done", analysis: NEW })).toBe(NEW);
  });

  test("재분석 중이거나 재분석에 실패했으면 옛 결과다", () => {
    expect(analysisOf({ status: "reanalyzing", previous: OLD })).toBe(OLD);
    expect(analysisOf({ status: "failed", previous: OLD })).toBe(OLD);
  });

  test("끝나기 전이나 옛 결과 없이 실패했으면 없다", () => {
    expect(analysisOf(undefined)).toBeUndefined();
    expect(
      analysisOf({ status: "translated", translation: translation("번역") }),
    ).toBeUndefined();
    expect(analysisOf({ status: "failed" })).toBeUndefined();
  });
});

describe("확인 중 구간과 먼저 온 단어", () => {
  const early: SentenceResult = {
    status: "early",
    earlyGrammar: [],
    checking: [checking(1)],
    earlyWords: [word("行く")],
  };

  test("분석을 기다리는 동안에만 보인다", () => {
    expect(checkingOf(early)).toEqual([checking(1)]);
    expect(earlyWordsOf(early)).toEqual([word("行く")]);
  });

  test("끝나거나 실패하면 지운다", () => {
    expect(checkingOf({ status: "done", analysis: NEW })).toEqual([]);
    expect(earlyWordsOf({ status: "done", analysis: NEW })).toEqual([]);
    expect(checkingOf({ status: "failed" })).toEqual([]);
    expect(earlyWordsOf({ status: "failed" })).toEqual([]);
  });

  test("번역만 왔고 값이 없으면 빈 목록이다", () => {
    const translated: SentenceResult = {
      status: "translated",
      translation: translation("번역"),
    };

    expect(checkingOf(translated)).toEqual([]);
    expect(earlyWordsOf(translated)).toEqual([]);
  });
});

describe("지금 보일 문법", () => {
  test("분석이 있으면 분석의 문법이다", () => {
    expect(grammarOf({ status: "done", analysis: NEW })).toEqual([
      grammar("새 문법"),
    ]);
  });

  test("분석이 없으면 먼저 온 문법이다", () => {
    expect(
      grammarOf({
        status: "failed",
        earlyGrammar: [grammar("확정 문법")],
      }),
    ).toEqual([grammar("확정 문법")]);
  });

  test("아무것도 오지 않았으면 비어 있다", () => {
    expect(grammarOf(undefined)).toEqual([]);
    expect(grammarOf({ status: "failed" })).toEqual([]);
  });
});

describe("지금 보일 번역", () => {
  test("옛 결과가 있으면 그 사이 받은 번역보다 옛 결과를 보인다", () => {
    expect(
      translationOf({
        status: "failed",
        previous: OLD,
        translation: translation("새 번역"),
      }),
    ).toBe(OLD);
  });

  test("분석이 없으면 받은 번역이다", () => {
    const shown = translation("번역");

    expect(translationOf({ status: "translated", translation: shown })).toBe(
      shown,
    );
  });

  test("번역이 오지 않았으면 없다", () => {
    expect(translationOf(undefined)).toBeUndefined();
    expect(
      translationOf({ status: "early", earlyGrammar: [], checking: [] }),
    ).toBeUndefined();
  });
});

describe("분석하지 못한 사유 문구", () => {
  test("시작 전에 거부한 사유는 그 문구다", () => {
    expect(refusalOf("ANALYSIS:USAGE_LIMIT")).toBe(
      "오늘 쓸 수 있는 분석량을 다 썼습니다. 내일 다시 시도해 주세요.",
    );
    expect(refusalOf("ANALYSIS:TEXT_TOO_LONG")).toBe(
      "문장이 너무 깁니다. 1,000자 이하로 나눠서 드래그해 주세요.",
    );
  });

  test("그 밖의 실패는 '분석하지 못했습니다'다", () => {
    expect(refusalOf("ANALYSIS:FAILED")).toBe("분석하지 못했습니다");
    expect(refusalOf(undefined)).toBe("분석하지 못했습니다");
  });
});
