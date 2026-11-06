import type {
  Analysis,
  CheckingItem,
  GrammarItem,
  Translation,
  WordItem,
} from "@/utils/api";

// 문장 하나의 분석 결과. 없으면 아직 아무것도 오지 않았다. early는 번역보다 먼저 온
// grammar 이벤트(LLM 없이 확정한 문법 earlyGrammar, 판별 대상 구간 checking)만 와서
// 번역을 기다리는 중이다. translated는 번역이 와서 문법·단어를 기다리는 중이다(번역은 아직 쓰는
// 중인 검증 전 앞부분일 수 있다, #303). failed에 번역이
// 있으면 번역 뒤 문법·단어에서 실패했다. earlyGrammar는 analysis가 오기 전까지 보이고(judged
// 이벤트가 오면 첫 LLM 응답이 판정한 문법이 더해진다, #97), 실패하면 LLM 없이 확정한 문법만 남는다.
// checking은 실패하면 지운다. earlyWords는 같은 grammar 이벤트로 먼저 온 사전 단어(뜻을 준비하는
// 중인 단어 포함)와 judged 이벤트로 바뀐 단어(#97)이고, analysis가 오면 그 단어로 바뀌며 실패하면 지운다. reanalyzing은 stale 분석의 옛 결과(previous)를 보이며 새 결과를
// 기다리는 중(재분석 중)이고, 그러다 실패하면 failed에 옛 결과만 남는다.
export type SentenceResult =
  | {
      status: "early";
      earlyGrammar: GrammarItem[];
      checking: CheckingItem[];
      earlyWords?: WordItem[];
    }
  | {
      status: "translated";
      translation: Translation;
      earlyGrammar?: GrammarItem[];
      checking?: CheckingItem[];
      earlyWords?: WordItem[];
    }
  | { status: "done"; analysis: Analysis }
  | { status: "reanalyzing"; previous: Analysis }
  | {
      status: "failed";
      translation?: Translation;
      earlyGrammar?: GrammarItem[];
      previous?: Analysis;
      // 서버가 분석을 시작하기 전에 거부한 오류 코드
      code?: string;
    };

// 분석을 시작하기 전에 거부된 사유별 문구(#28). 그 밖의 실패는 '분석하지 못했습니다'다.
const REFUSALS: Record<string, string> = {
  "ANALYSIS:USAGE_LIMIT":
    "오늘 쓸 수 있는 분석량을 다 썼습니다. 내일 다시 시도해 주세요.",
  "ANALYSIS:TOO_MANY_REQUESTS":
    "동시에 분석하는 문장이 너무 많습니다. 잠시 뒤 다시 시도해 주세요.",
  "ANALYSIS:TEXT_TOO_LONG":
    "문장이 너무 깁니다. 1,000자 이하로 나눠서 드래그해 주세요.",
};

// 지금 보일 완성된 분석. 분석이 끝났으면 그 결과, 다시 분석하는 중이거나 그러다 실패했으면 옛 결과다.
export function analysisOf(result: SentenceResult | undefined) {
  if (result?.status === "done") return result.analysis;
  if (result?.status === "reanalyzing" || result?.status === "failed") {
    return result.previous;
  }
  return undefined;
}

// 지금 보일 판별 대상 구간(확인 중). 분석이 끝나거나 실패하면 없다.
export function checkingOf(result: SentenceResult | undefined) {
  if (result?.status === "early" || result?.status === "translated") {
    return result.checking ?? [];
  }
  return [];
}

// 분석이 끝나기 전에 먼저 온 단어. 분석이 끝나거나 실패하면 없다.
export function earlyWordsOf(result: SentenceResult | undefined) {
  if (result?.status === "early" || result?.status === "translated") {
    return result.earlyWords ?? [];
  }
  return [];
}

// 지금 보일 문법. 분석이 끝나기 전에는 먼저 온 문법만 보인다.
export function grammarOf(result: SentenceResult | undefined) {
  const analysis = analysisOf(result);
  if (analysis) return analysis.grammar;
  return result && "earlyGrammar" in result ? (result.earlyGrammar ?? []) : [];
}

// 지금 보일 번역과 루비
export function translationOf(result: SentenceResult | undefined) {
  const analysis = analysisOf(result);
  if (analysis) return analysis;
  return result && "translation" in result ? result.translation : undefined;
}

// 분석하지 못한 사유 문구
export function refusalOf(code: string | undefined) {
  return REFUSALS[code ?? ""] ?? "분석하지 못했습니다";
}
