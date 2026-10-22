// 개발 빌드 기본값은 로컬 compose 백엔드다. 바꾸려면 빌드할 때 WXT_API_BASE_URL을 준다.
export const API_BASE_URL =
  import.meta.env.WXT_API_BASE_URL ?? "http://localhost:8000";

export interface GrammarItem {
  // 원문(보낸 문장) 기준 UTF-16 위치 [start, end). 자바스크립트 문자열 위치와 같다.
  start: number;
  end: number;
  // decided는 용법이 정해진 구간, divergent는 해석 갈림(name·explanation_ko는 주 용법),
  // unresolved는 미확정(name은 패턴 이름, 설명 없음)이다.
  state: "decided" | "divergent" | "unresolved";
  name: string;
  explanation_ko: string | null;
  // pending은 LLM이 썼고 아직 검수되지 않은 문법이다.
  review_status: "pending" | "approved";
  // 해석 갈림의 대안 해석(대안 용법 이름, 그 해석으로 옮긴 문장 전체 번역). 반려된 대안은 빠진다.
  alternatives?: Alternative[];
}

export interface Alternative {
  name: string;
  translation_ko: string;
  review_status: "pending" | "approved";
}

// 판별 대상 구간(LLM 판별을 기다리는 후보 구간, 화면의 '확인 중'). 원문 기준 UTF-16 위치와 후보 용법 이름(서버가 매긴 순서)
export interface CheckingItem {
  start: number;
  end: number;
  // 후보 이름도 LLM이 만든 지식이라 검수 상태를 함께 받는다(pending이면 미검수).
  candidates: { name: string; review_status: "pending" | "approved" }[];
}

export interface WordItem {
  // 원문 기준 UTF-16 위치 [start, end). 문장에 나온 그 단어(활용형 포함)의 자리다.
  start: number;
  end: number;
  // 사전형과 그 읽기(食べて → 食べる / たべる), 이 문장에서의 뜻
  lemma: string;
  reading: string;
  meaning_ko: string;
  // pending은 JMdict 없이 LLM이 만든 뜻이라 아직 검수되지 않았다.
  review_status: "pending" | "approved";
}

export interface RubyItem {
  // 원문 기준 UTF-16 위치 [start, end). 한자 부분만 덮는다(食べる → 食).
  start: number;
  end: number;
  // SudachiPy 추정 읽기(히라가나)
  reading: string;
}

export interface Analysis {
  translation_ko: string;
  grammar: GrammarItem[];
  words: WordItem[];
  ruby: RubyItem[];
}

// 문법·단어보다 먼저 오는 번역과 루비
export interface Translation {
  translation_ko: string;
  ruby: RubyItem[];
}

// 분석 실패. 실패 전에 받은 번역과 먼저 온 문법(LLM 없이 확정한 구간), stale 분석의 옛 결과를
// 함께 싣는다.
export class AnalysisFailed extends Error {
  constructor(
    readonly translation?: Translation,
    readonly earlyGrammar?: GrammarItem[],
    readonly previous?: Analysis,
  ) {
    super("분석 실패");
  }
}

// 서버는 줄 단위 JSON으로 translation(번역, 루비) → analysis(번역, 문법, 단어)를 보내고,
// 실패하면 error를 보낸다. LLM 없이 확정한 문법이나 판별 대상 구간이 있으면 그보다 먼저
// grammar(확정 문법, 판별 대상 구간)를 보낸다. 실패(AnalysisFailed)에는 받은 확정 문법만 싣고,
// 판별 대상 구간은 싣지 않는다(화면에서 지운다). stale 분석이면 맨 먼저 previous(옛 번역, 루비,
// 문법, 단어)를 보내고 onPrevious를 부른다. 이어지는 이벤트는 다시 분석하는 흐름 그대로다.
// 패턴 세트 버전이 올라 다시 매칭한 캐시 문장에 판별 대상 새 구간이 있으면 같은 순서로
// grammar(저장 문법과 새 확정 문법, 새 판별 대상 구간) → translation(저장 번역) → analysis를
// 보낸다. 재판정이 실패해도 error 없이 저장 결과로 analysis를 보낸다(#41).
// grammar가 오면 onEarlyGrammar를, 번역이 오면 onTranslation을 부르고, 다 오면 분석 전체를
// 돌려준다. analysis의 번역은 문법·단어와 짝인 저장된 번역이라 그것을 쓴다.
export async function analyzeSentence(
  text: string,
  onTranslation: (translation: Translation) => void,
  onEarlyGrammar?: (grammar: GrammarItem[], checking: CheckingItem[]) => void,
  onPrevious?: (previous: Analysis) => void,
): Promise<Analysis> {
  const response = await fetch(`${API_BASE_URL}/api/analyses/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok || !response.body) throw new AnalysisFailed();
  let translation: Translation | undefined;
  let earlyGrammar: GrammarItem[] | undefined;
  let previous: Analysis | undefined;
  try {
    for await (const event of ndjsonEvents(response.body)) {
      if (event.type === "previous") {
        previous = {
          translation_ko: event.translation_ko,
          grammar: event.grammar,
          words: event.words,
          ruby: event.ruby,
        };
        onPrevious?.(previous);
      } else if (event.type === "grammar") {
        earlyGrammar = event.grammar;
        onEarlyGrammar?.(earlyGrammar, event.checking);
      } else if (event.type === "translation") {
        translation = {
          translation_ko: event.translation_ko,
          ruby: event.ruby,
        };
        onTranslation(translation);
      } else if (event.type === "analysis") {
        return {
          translation_ko: event.translation_ko,
          grammar: event.grammar,
          words: event.words,
          ruby: translation?.ruby ?? [],
        };
      } else {
        break;
      }
    }
  } catch {
    // 연결이 끊기거나 줄이 JSON이 아니어도 이미 받은 번역은 남긴다.
  }
  // error 이벤트를 받았거나, analysis 전에 스트림이 끝났거나 끊겼다.
  throw new AnalysisFailed(translation, earlyGrammar, previous);
}

type StreamEvent =
  | ({ type: "previous" } & Analysis)
  | { type: "grammar"; grammar: GrammarItem[]; checking: CheckingItem[] }
  | ({ type: "translation" } & Translation)
  | ({ type: "analysis" } & Omit<Analysis, "ruby">)
  | { type: "error"; error: string };

// 바이트 스트림을 줄마다 JSON 이벤트로 읽는다. 줄은 조각 경계에서 잘려 올 수 있다.
async function* ndjsonEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffered += decoder.decode(value, { stream: true });
      const lines = buffered.split("\n");
      buffered = lines.pop()!;
      for (const line of lines) {
        if (line.trim()) yield JSON.parse(line) as StreamEvent;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
