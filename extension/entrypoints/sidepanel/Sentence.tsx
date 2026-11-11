import { useState } from "react";
import type { GrammarItem, WordItem } from "@/utils/api";
import { AnalyzingStatus, RetryButton } from "./AnalysisStatus";
import { DisplayToggles } from "./DisplayToggles";
import { GrammarCards, HighlightedText } from "./Grammar";
import { cardAt, grammarCardCount } from "./grammar-groups";
import { namedWords, withNameRuby, wordKey } from "./named-words";
import { isAdded, isHidden } from "@/utils/my-items";
import type { HighlightStyle } from "@/utils/preferences";
import { HiddenCards, type HiddenCard, type MyItems } from "./MyItems";
import { ResultTabs, type ResultTab } from "./ResultTabs";
import { SelectedCard } from "./SelectedCard";
import { senseBadges } from "./sense-badges";
import {
  analysisOf,
  checkingOf,
  earlyWordsOf,
  grammarOf,
  refusalOf,
  translationOf,
  type SentenceResult,
} from "./sentence-result";
import type { NameActions } from "./Words";
import { wordRowCount } from "./word-groups";

// 문장 한 페이지: 원문 카드(원문, 번역) → 문법·단어 탭 → 탭 내용
export function SentenceView({
  text,
  showRuby,
  onToggleRuby,
  highlightStyle,
  onHighlightStyleChange,
  result,
  tab,
  onTabChange,
  onRetry,
  names,
  onSave,
  onRemove,
  items,
  initialSelected,
}: {
  text: string;
  showRuby: boolean;
  onToggleRuby: () => void;
  highlightStyle: HighlightStyle;
  onHighlightStyleChange: (style: HighlightStyle) => void;
  result: SentenceResult | undefined;
  tab: ResultTab;
  onTabChange: (tab: ResultTab) => void;
  // 실패한 문장을 처음부터 다시 분석한다.
  onRetry: () => void;
  // 지정한 이름(표기 → 읽기, #136)
  names: ReadonlyMap<string, string | null>;
  // 내 일본어 항목(#321). '숨김'으로 숨긴 카드는 목록·형광펜·개수에서 빼고 맨 아래에 접어 둔다.
  items?: MyItems;
  // 처음부터 고른 글자의 위치. 가이드(#370) 장면이 '선택한 카드'를 열어 보일 때만 쓴다.
  initialSelected?: number;
} & NameActions) {
  // '사전 단어 보기' 토글로 고른 보기(자리 → 이름 행인가). 화면 상태라 저장하지 않는다.
  const [chosen, setChosen] = useState<ReadonlyMap<string, boolean>>(new Map());
  const chooseView = (key: string, named: boolean) =>
    setChosen((current) => new Map(current).set(key, named));
  // 원문을 눌러 고른 글자의 위치(#354). 화면 상태라 저장하지 않고 페이지마다 새로 시작한다.
  const [selected, setSelected] = useState<number | undefined>(initialSelected);
  const hiddenUsage = (item: GrammarItem) =>
    !!items && isHidden(items.states, "usage", item.usage_id);
  // 숨긴 용법은 바깥 카드에서도, 다른 카드의 구성 문법(parts)에서도 뺀다(PR #327 리뷰). 바깥을
  // 숨기면 묶인 구성 문법도 함께 숨긴다. 다시 분석할 때 독립 카드로 튀어나오지 않게 한다.
  const shownGrammar = (list: GrammarItem[]) =>
    list.flatMap((item) => {
      if (hiddenUsage(item)) return [];
      const parts = (item.parts ?? []).filter((p) => !hiddenUsage(p));
      return item.parts ? [{ ...item, parts }] : [item];
    });
  const analysis = analysisOf(result);
  const translation = translationOf(result);
  const allGrammar = grammarOf(result);
  const grammar = shownGrammar(allGrammar);
  const checking = checkingOf(result);
  const earlyWords = earlyWordsOf(result);
  // 탭에 보일 문법·단어. 분석이 끝나기 전에도 먼저 온 단어가 있으면 먼저 온 문법과 함께 탭으로
  // 보인다(#96). 문법 개수는 보이는 카드 수다(합친 카드는 한 장, 구성 문법의 하위 박스도 센다).
  const allWords = analysis ? analysis.words : earlyWords;
  // 이름 행으로 보이는 자리는 사전 뜻을 숨겨도 남긴다. 숨김은 사전 뜻 카드에만 쓴다(PR #327 리뷰).
  const named = new Set(
    namedWords(text, allWords, names, chosen, analysis?.name_spans).map(
      ({ word }) => wordKey(word),
    ),
  );
  const hiddenWord = (word: WordItem) =>
    !!items &&
    !named.has(wordKey(word)) &&
    isHidden(items.states, "sense", word.sense?.id);
  const shownWords = (list: WordItem[]) =>
    list.filter((word) => !hiddenWord(word));
  // '선택한 카드'(#354): 고른 글자의 문법 카드와 그 아래 그 글자의 단어 카드. 둘 다 사라지면
  // (숨김·재분석) 닫고, 다시 나타나도 저절로 열지 않는다.
  const visibleWords = shownWords(allWords);
  const selectedGrammar =
    selected === undefined ? undefined : cardAt(grammar, selected);
  const selectedWords =
    selected === undefined
      ? []
      : visibleWords.filter(
          (word) => word.start <= selected && selected < word.end,
        );
  if (
    selected !== undefined &&
    !selectedGrammar &&
    selectedWords.length === 0
  ) {
    setSelected(undefined);
  }
  const removeName = async (surface: string) => {
    await onRemove(surface);
    // 해제한 표기의 자리는 다시 지정해도 기본 보기로 시작한다.
    setChosen(
      (current) =>
        new Map(
          [...current].filter(
            ([key]) =>
              !allWords.some(
                (word) =>
                  wordKey(word) === key &&
                  text.slice(word.start, word.end) === surface,
              ),
          ),
        ),
    );
  };
  const tabbed = analysis
    ? {
        grammar,
        checking: [],
        words: shownWords(analysis.words),
        grammarCount: grammarCardCount(grammar),
      }
    : earlyWords.length > 0
      ? {
          grammar,
          checking,
          words: shownWords(earlyWords),
          grammarCount: grammarCardCount(grammar) + checking.length,
        }
      : undefined;
  const hiddenGrammar = hiddenCards(
    allGrammar
      .flatMap((item) => [item, ...(item.parts ?? [])])
      .filter(hiddenUsage),
    (item) => ({
      kind: "usage",
      id: item.usage_id!,
      chip: item.pattern_name,
      name: item.name,
      pending: item.review_status === "pending",
      translated: false,
      added: !!items && isAdded(items.states, "usage", item.usage_id),
    }),
  );
  const hiddenWords = hiddenCards(allWords.filter(hiddenWord), (word) => ({
    kind: "sense",
    id: word.sense!.id!,
    chip: word.dictionary_form,
    name: word.sense!.meaning_ko ?? "",
    ...senseBadges(word.sense),
    added: !!items && isAdded(items.states, "sense", word.sense?.id),
  }));
  // 단어 개수도 보이는 행 수다(합친 행은 한 행, #211).
  const wordCount = tabbed
    ? wordRowCount(text, tabbed.words, names, analysis?.name_spans)
    : 0;
  const ruby = translation?.ruby ?? [];
  const wordList = {
    text,
    ruby,
    names,
    chosen,
    nameSpans: analysis?.name_spans,
    onChooseView: chooseView,
    onSave,
    onRemove: removeName,
    items,
  };
  const shownRuby = withNameRuby(
    ruby,
    namedWords(text, allWords, names, chosen, analysis?.name_spans),
  );
  return (
    <>
      <section className="sentence-card" aria-label="원문">
        <div className="display-toggles">
          {result?.status === "reanalyzing" && (
            <p role="status" aria-label="재분석 중" className="reanalysis">
              재분석 중
            </p>
          )}
          {result?.status === "failed" && result.previous && (
            <p className="reanalysis error">
              재분석하지 못했습니다 <RetryButton onRetry={onRetry} />
            </p>
          )}
          <DisplayToggles
            showRuby={showRuby}
            onToggleRuby={onToggleRuby}
            highlightStyle={highlightStyle}
            onHighlightStyleChange={onHighlightStyleChange}
          />
        </div>
        <p
          lang="ja"
          className={
            highlightStyle === "underline" ? "original underline" : "original"
          }
        >
          <HighlightedText
            text={text}
            grammar={grammar}
            checking={checking}
            words={visibleWords}
            ruby={showRuby ? shownRuby : []}
            selected={selected}
            onSelect={(at) =>
              setSelected((current) => (current === at ? undefined : at))
            }
          />
        </p>
        <hr />
        {(!result || result.status === "early") && (
          <div
            role="status"
            aria-label="번역을 불러오는 중"
            className="skeleton"
          >
            <span />
            <span />
          </div>
        )}
        {translation && (
          <p className="translation">{translation.translation_ko}</p>
        )}
        {selected !== undefined && (
          <SelectedCard
            grammar={selectedGrammar}
            words={selectedWords}
            wordList={wordList}
            onClose={() => setSelected(undefined)}
          />
        )}
        {result?.status === "failed" && !translation && (
          <p className="error">
            {refusalOf(result.code)} <RetryButton onRetry={onRetry} />
          </p>
        )}
      </section>
      {!tabbed &&
        grammar.length + checking.length + hiddenGrammar.length > 0 && (
          <div className="below-card">
            {grammar.length + checking.length > 0 && (
              <GrammarCards
                text={text}
                grammar={grammar}
                checking={checking}
                items={items}
              />
            )}
            {/* 탭 없이 먼저 온 문법만 남은 화면(번역 뒤 실패 등)에서도 숨긴 카드를 되돌릴 수 있게 한다. */}
            {items && <HiddenCards cards={hiddenGrammar} items={items} />}
          </div>
        )}
      {result?.status === "translated" && !tabbed && (
        <AnalyzingStatus className="below-card" />
      )}
      {result?.status === "failed" && !analysis && translation && (
        <p className="error below-card">
          문법·단어를 분석하지 못했습니다 <RetryButton onRetry={onRetry} />
        </p>
      )}
      {tabbed && (
        <ResultTabs
          tab={tab}
          onTabChange={onTabChange}
          analyzed={!!analysis}
          grammar={tabbed.grammar}
          checking={tabbed.checking}
          grammarCount={tabbed.grammarCount}
          words={tabbed.words}
          wordCount={wordCount}
          hiddenGrammar={hiddenGrammar}
          hiddenWords={hiddenWords}
          wordList={wordList}
        />
      )}
    </>
  );
}

// 숨긴 항목을 칸 하나에 한 번만 접어 둘 카드로 만든다(합친 카드처럼 같은 용법·뜻은 한 장).
function hiddenCards<T>(
  list: T[],
  fields: (item: T) => Omit<HiddenCard, "key">,
): HiddenCard[] {
  const cards = new Map<string, HiddenCard>();
  for (const item of list) {
    const card = fields(item);
    const key = `${card.kind}:${card.id}`;
    if (!cards.has(key)) cards.set(key, { key, ...card });
  }
  return [...cards.values()];
}
