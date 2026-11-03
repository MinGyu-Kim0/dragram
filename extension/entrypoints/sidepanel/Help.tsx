import type { ReactNode, Ref } from "react";
import type { Analysis, CheckingItem, GrammarItem } from "@/utils/api";
import { itemKey } from "@/utils/my-items";
import { GrammarCards } from "./Grammar";
import { HiddenCards, type MyItems } from "./MyItems";
import { SentenceView } from "./Sentence";
import { WordList } from "./Words";

// 헤더 도움말 버튼(#365). 닫으면 포커스가 이 버튼으로 돌아온다(useHelp).
export function HelpButton({
  ref,
  open,
  onToggle,
}: {
  ref: Ref<HTMLButtonElement>;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      ref={ref}
      type="button"
      className="theme-button help-button"
      aria-label="도움말"
      aria-expanded={open}
      onClick={onToggle}
    >
      ?
    </button>
  );
}

// 예시 문장. 사용자 원문이 아니라 도움말용으로 새로 쓴 문장이다.
const TEXT = "田中さんは雨が降っちゃったので、出かけられなかった。";

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

const RARERU_UNRESOLVED: GrammarItem = {
  ...RARERU,
  usage_id: null,
  state: "unresolved",
  name: "られる",
  explanation_ko: null,
  korean_equivalent: null,
  function_tags: [],
  alternatives: [],
};

const RARERU_CHECKING: CheckingItem = {
  start: 19,
  end: 21,
  pattern_name: "られる",
  candidates: [
    { name: "가능", review_status: "approved" },
    { name: "존경", review_status: "pending" },
  ],
};

// 구성 문법 예시
const PARTS_TEXT = "行かなければならない。";

const NAKEREBA: GrammarItem = {
  ...base,
  start: 2,
  end: 10,
  pattern_name: "なければならない",
  usage_id: 4,
  state: "decided",
  name: "의무",
  explanation_ko: "그렇게 해야 함을 나타내요.",
  korean_equivalent: "~해야 한다",
  function_tags: ["obligation"],
  parts: [
    {
      ...base,
      start: 5,
      end: 6,
      pattern_name: "ば",
      usage_id: 5,
      state: "decided",
      name: "조건",
      explanation_ko: "앞 내용이 뒤 내용의 조건임을 나타내요.",
      korean_equivalent: "~하면",
      pos_tags: ["particle"],
      function_tags: ["conditional"],
    },
  ],
};

const ANALYSIS: Analysis = {
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

// 예시의 버튼은 아무것도 저장하지 않는다. 예시 항목이 내 일본어에 들어가지 않게 한다.
const nothing = () => Promise.resolve();
const noop = () => {};

const ITEMS: MyItems = {
  states: new Map([[itemKey("usage", 2), { added: true, hidden: false }]]),
  withExamples: new Set(),
  save: nothing,
};

// 실제 패널 컴포넌트로 그린 예시. 눌러지지 않는 그림이다.
function Example({ children }: { children: ReactNode }) {
  return (
    <figure className="help-example" inert aria-label="예시">
      {children}
    </figure>
  );
}

function Topic({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="help-topic">
      <summary>{title}</summary>
      <div className="help-body">{children}</div>
    </details>
  );
}

export function Help({ onClose }: { onClose: () => void }) {
  const names = new Map<string, string | null>();
  return (
    <section className="help" aria-labelledby="help-title">
      <div className="help-head">
        <h2 id="help-title">도움말</h2>
        <button type="button" className="text-button" onClick={onClose}>
          닫기
        </button>
      </div>
      <p className="help-lead">
        Dragram은 웹페이지에서 고른 일본어 문장을 분석해 문법·단어·한자를 보여
        줘요. 궁금한 항목을 눌러 펼쳐 보세요. 예시는 실제 화면과 같은 모양이지만
        눌러도 아무것도 바뀌지 않아요.
      </p>

      <Topic title="시작하기">
        <p>
          웹페이지의 일본어 문장을 드래그해 고른 뒤, 마우스 오른쪽 버튼을 눌러{" "}
          <strong>Dragram으로 분석</strong>을 고르세요. 이 패널에 결과가 나와요.
        </p>
        <p>
          여러 문장을 한 번에 고르면 문장마다 페이지로 나뉘어요. 위의{" "}
          <strong>‹ 1 / N ›</strong>로 넘겨 보세요.
        </p>
        <p>
          왼쪽 위 로고를 누르면 웹이 열려요. 추가한 내 일본어와 학습 카드는
          웹에서 봐요.
        </p>
      </Topic>

      <Topic title="원문 카드와 탭">
        <Example>
          <SentenceView
            text={TEXT}
            showRuby
            onToggleRuby={noop}
            highlightStyle="marker"
            onHighlightStyleChange={noop}
            result={{ status: "done", analysis: ANALYSIS }}
            tab="grammar"
            onTabChange={noop}
            onRetry={noop}
            names={names}
            onSave={nothing}
            onRemove={nothing}
          />
        </Example>
        <dl>
          <dt>후리가나</dt>
          <dd>한자 위 읽기를 켜고 꺼요.</dd>
          <dt>형광펜 · 밑줄</dt>
          <dd>문법 구간을 칠할지 밑줄로 보일지 골라요. 고른 값은 기억돼요.</dd>
          <dt>원문의 칠해진 부분</dt>
          <dd>
            누르면 그 부분의 문법 카드와 단어를 원문 아래에 모아 보여 줘요.
          </dd>
          <dt>번역</dt>
          <dd>구분선 아래 한국어는 AI가 옮긴 번역이에요.</dd>
          <dt>문법 N · 단어 N</dt>
          <dd>이 문장의 문법 카드와 단어를 탭으로 나눠 보여 줘요.</dd>
        </dl>
      </Topic>

      <Topic title="문법 카드 읽기">
        <Example>
          <GrammarCards text={TEXT} grammar={[CHAU]} />
        </Example>
        <dl>
          <dt>칩과 이름</dt>
          <dd>
            칩은 문법의 기본형, 옆은 한국어 이름이에요. 문장 속 모양이 다르면{" "}
            <strong>문장 속 형태</strong> 줄에 원문 모양을 보여 줘요.
          </dd>
          <dt>AI 생성·미검수</dt>
          <dd>
            AI가 만들었고 아직 사람이 확인하지 않은 설명이에요. 틀릴 수 있어요.
            배지가 없으면 검수를 마친 내용이에요.
          </dd>
          <dt>회화체</dt>
          <dd>
            말할 때 줄여 쓰는 형태예요. 원형이 있으면 「てしまう」의 회화체처럼
            알려 줘요.
          </dd>
          <dt>태그 · 뜻 · 설명</dt>
          <dd>
            회색 태그는 품사·기능, <strong>뜻</strong>은 주로 옮겨지는 한국어
            표현, <strong>설명</strong>은 용법 설명이에요.
          </dd>
        </dl>
        <h3 className="help-subtitle">이런 카드도 있어요</h3>
        <Example>
          <GrammarCards text={TEXT} grammar={[RARERU]} />
        </Example>
        <p>
          <strong>다른 해석</strong>이 붙은 카드는 한 구간이 두 가지로 읽힐 수
          있다는 뜻이에요. 위가 더 그럴듯한 해석이고, 아래 줄이 다른 해석으로
          옮긴 문장이에요.
        </p>
        <Example>
          <GrammarCards text={TEXT} grammar={[]} checking={[RARERU_CHECKING]} />
        </Example>
        <p>
          점선 <strong>확인 중</strong> 카드는 아직 어느 뜻인지 판단하는 중인
          구간이에요. 잠시 뒤 결과로 바뀌어요.
        </p>
        <Example>
          <GrammarCards text={TEXT} grammar={[RARERU_UNRESOLVED]} />
        </Example>
        <p>
          <strong>판단하지 못함</strong>은 문맥만으로 용법을 정하지 못한
          구간이에요. 오류가 아니에요.
        </p>
        <Example>
          <GrammarCards text={PARTS_TEXT} grammar={[NAKEREBA]} />
        </Example>
        <p>
          카드 안의 작은 상자는 그 문법 안에 들어 있는{" "}
          <strong>구성 문법</strong>이에요.
        </p>
      </Topic>

      <Topic title="단어·한자">
        <Example>
          <WordList
            text={TEXT}
            words={ANALYSIS.words}
            ruby={ANALYSIS.ruby}
            names={names}
            chosen={new Map()}
            nameSpans={ANALYSIS.name_spans}
            onChooseView={noop}
            onSave={nothing}
            onRemove={nothing}
          />
        </Example>
        <dl>
          <dt>표제 · 읽기 · 뜻</dt>
          <dd>
            사전형과 그 읽기, 이 문장에서 고른 뜻이에요. 태그는 품사·동사 그룹
            등이에요.
          </dd>
          <dt>AI 번역</dt>
          <dd>사전 뜻을 AI가 한국어로 옮겼고 아직 검수하지 않았어요.</dd>
          <dt>인명 · 지명</dt>
          <dd>이 단어가 사람 이름이나 땅 이름으로 쓰였다는 표시예요.</dd>
          <dt>이름으로 지정</dt>
          <dd>
            사람·땅 이름이 뜻으로 풀렸으면 이름으로 지정하고 읽기를 정해 두세요.
            그 표기를 이름으로 보여 주고, 내 화면에만 적용돼요.
          </dd>
        </dl>
      </Topic>

      <Topic title="내 일본어와 숨김">
        <Example>
          <GrammarCards text={TEXT} grammar={[CHAU, NODE]} items={ITEMS} />
          <HiddenCards
            cards={[
              {
                key: itemKey("sense", 12),
                kind: "sense",
                id: 12,
                chip: "雨",
                name: "비",
                pending: false,
                translated: false,
                added: false,
              },
            ]}
            items={ITEMS}
          />
        </Example>
        <dl>
          <dt>추가 · ✓ 추가됨</dt>
          <dd>
            <strong>추가</strong>를 누르면 그 문법·단어 뜻이 내 일본어에
            들어가요. <strong>✓ 추가됨</strong>을 다시 누르면 내 일본어에서
            제외해요. 제외하면 저장한 예문도 지워져요.
          </dd>
          <dt>예문 저장</dt>
          <dd>
            추가한 항목에 이 문장을 예문으로 남겨요. 웹에서 함께 복습해요.
          </dd>
          <dt>숨김</dt>
          <dd>
            이 패널에서만 카드를 접어 둬요. 내 일본어 추가와는 따로라 기록은
            그대로예요. 숨긴 문법은 형광펜과 탭 개수에서도 빠져요.
          </dd>
          <dt>숨긴 카드 N개</dt>
          <dd>
            탭 맨 아래에서 펼쳐 <strong>복원</strong>하면 숨기기 전으로
            돌아와요.
          </dd>
        </dl>
      </Topic>

      <Topic title="막혔을 때">
        <dl>
          <dt>다시 시도</dt>
          <dd>
            분석하지 못한 문장 옆의 버튼을 누르면 그 문장을 다시 분석해요.
          </dd>
          <dt>분석량 · 동시 요청 안내</dt>
          <dd>
            하루에 쓸 수 있는 분석량을 다 썼거나 한꺼번에 너무 많이 보냈다는
            뜻이에요. 안내에 적힌 때에 다시 시도해 주세요.
          </dd>
          <dt>로그인이 필요해요</dt>
          <dd>
            웹에서 Google 계정으로 로그인하고 확장 프로그램을 연결하면 분석할 수
            있어요.
          </dd>
        </dl>
      </Topic>
    </section>
  );
}
