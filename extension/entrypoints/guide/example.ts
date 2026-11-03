import type { Analysis, GrammarItem } from "@/utils/api";
import { itemKey } from "@/utils/my-items";
import type { MyItems } from "../sidepanel/MyItems";

// 가이드(#370) 장면의 예시 문장과 분석. 사용자 원문이 아니라 가이드용으로 새로 쓴 문장이다.
// 미검수 배지 규칙은 실제 카드와 같다(ちゃう 용법, 존경 해석, 出かける의 AI 번역).
export const TEXT = "田中さんは雨が降っちゃったので、出かけられなかった。";

const base = {
  korean_equivalent_review_status: "approved",
  pos_tags: [] as string[],
  function_tags_review_status: "approved",
  review_status: "approved",
  register: "standard",
  variant_of: null,
} as const;

const CHAU: GrammarItem = {
  ...base,
  start: 9,
  end: 12,
  pattern_name: "ちゃう",
  usage_id: 1,
  state: "decided",
  name: "완료·유감",
  explanation_ko:
    "동작이 끝나 버렸음을 나타내요. 아쉬움이나 뜻밖이라는 느낌이 함께 담길 때가 많아요.",
  korean_equivalent: "~해 버리다",
  function_tags: ["perfective"],
  review_status: "pending",
  register: "colloquial",
  variant_of: "てしまう",
};

const NODE: GrammarItem = {
  ...base,
  start: 13,
  end: 15,
  pattern_name: "ので",
  usage_id: 2,
  state: "decided",
  name: "원인·이유",
  explanation_ko: "앞 내용이 뒤 내용의 원인이나 이유임을 나타내요.",
  korean_equivalent: "~해서, ~니까",
  pos_tags: ["particle"],
  function_tags: ["cause"],
};

const RARERU: GrammarItem = {
  ...base,
  start: 19,
  end: 21,
  pattern_name: "られる",
  usage_id: 3,
  state: "divergent",
  name: "가능",
  explanation_ko: "그 동작을 할 수 있음을 나타내요.",
  korean_equivalent: "~할 수 있다",
  pos_tags: ["auxiliary_verb"],
  function_tags: ["potential"],
  alternatives: [
    {
      name: "존경",
      korean_equivalent: "~하시다",
      korean_equivalent_review_status: "pending",
      function_tags: ["honorific"],
      function_tags_review_status: "pending",
      translation_ko: "다나카 씨는 비가 와 버려서 외출하지 않으셨다.",
      review_status: "pending",
    },
  ],
};

export const ANALYSIS: Analysis = {
  translation_ko: "다나카 씨는 비가 와 버려서 외출하지 못했다.",
  grammar: [CHAU, NODE, RARERU],
  words: [
    {
      start: 0,
      end: 2,
      dictionary_form: "田中",
      reading: "たなか",
      tags: ["noun", "proper_noun"],
      in_dictionary: true,
      sense: {
        id: 11,
        tags: [],
        gloss_en: [],
        origin: "jmdict",
        status: "approved",
        meaning_ko: "다나카(성)",
        meaning_status: "reviewed",
      },
    },
    {
      start: 5,
      end: 6,
      dictionary_form: "雨",
      reading: "あめ",
      tags: ["noun"],
      in_dictionary: true,
      sense: {
        id: 12,
        tags: [],
        gloss_en: [],
        origin: "jmdict",
        status: "approved",
        meaning_ko: "비",
        meaning_status: "reviewed",
      },
    },
    {
      start: 16,
      end: 19,
      dictionary_form: "出かける",
      reading: "でかける",
      tags: ["verb", "group2"],
      in_dictionary: true,
      sense: {
        id: 13,
        tags: ["intransitive"],
        gloss_en: [],
        origin: "jmdict",
        status: "approved",
        meaning_ko: "외출하다, 나가다",
        meaning_status: "ai",
      },
    },
  ],
  ruby: [
    { start: 0, end: 2, reading: "たなか" },
    { start: 5, end: 6, reading: "あめ" },
    { start: 7, end: 8, reading: "ふ" },
    { start: 16, end: 17, reading: "で" },
  ],
  name_spans: [{ start: 0, end: 2, type: "person" }],
};

// 장면의 버튼은 아무것도 저장하지 않는다. 예시 항목이 내 일본어에 들어가지 않게 한다.
export const nothing = () => Promise.resolve();
export const noop = () => {};

export const ITEMS: MyItems = {
  // ので는 추가한 카드, 雨는 숨긴 카드로 보인다.
  states: new Map([
    [itemKey("usage", 2), { added: true, hidden: false }],
    [itemKey("sense", 12), { added: false, hidden: true }],
  ]),
  withExamples: new Set(),
  save: nothing,
};
