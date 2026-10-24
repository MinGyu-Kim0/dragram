import { clearTokenIfStill, loadToken, signOutIfStill } from "./auth";

// 개발 빌드 기본값은 로컬 compose 백엔드다. 바꾸려면 빌드할 때 WXT_API_BASE_URL을 준다.
// 끝 슬래시는 떼어 /api 경로를 붙일 때 //가 생기지 않게 한다(경로 접두어는 남긴다).
export const API_BASE_URL = (
  import.meta.env.WXT_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

// 확장 토큰이 없거나 서버가 AUTH:LOGIN_REQUIRED(401)로 거부했다. 저장한 토큰은 지운다.
export class LoginRequired extends Error {
  constructor() {
    super("로그인 필요");
  }
}

// 확장 로그아웃: 저장한 토큰을 먼저 지운 뒤 서버에서 이 토큰만 폐기한다. 서버가 응답하지
// 않아도 로컬 로그아웃은 끝난다.
export async function logoutExtension(): Promise<void> {
  const token = await loadToken();
  if (!token) return;
  // 그사이 웹에서 다시 연결해 새 토큰이 왔으면 그것은 지우지 않는다.
  await signOutIfStill(token);
  try {
    await fetch(`${API_BASE_URL}/api/auth/extension-tokens/revoke/`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    // 서버에 남은 토큰은 마지막 사용 후 90일이 지나면 쓸 수 없다.
  }
}

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
  // 매칭된 패턴의 말투. colloquial이면 회화체 패턴(ちゃう 등)이다.
  register: "standard" | "colloquial";
  // 회화체가 연결된 원형 패턴 이름(てしまう 등). 연결되지 않았으면 null이다.
  variant_of: string | null;
  // 해석 갈림의 대안 해석(대안 용법 이름, 그 해석으로 옮긴 문장 전체 번역). 반려된 대안은 빠진다.
  alternatives?: Alternative[];
  // 이 구간 안에 완전히 들어가는 구성 문법(원문 순서, 한 단). analysis·previous 이벤트에만
  // 있고, 바깥 패턴이 구성 문법을 숨기게 돼 있으면 서버가 뺀다.
  parts?: GrammarItem[];
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
  // JMdict 표제(사전형)와 이 표기에 맞는 읽기(食べて → 食べる / たべる)
  dictionary_form: string;
  reading: string;
  // 단어 전체 태그(품사, 동사 그룹 등) 코드
  tags: string[];
  // 사전(JMdict) 단어인가. 아니면 LLM이 만든 단어다(#134).
  in_dictionary: boolean;
  // 이 문장에서 고른 뜻. null이면 뜻이 여럿이라 LLM이 아직 고르지 않았다(화면은 '뜻을 준비하는
  // 중').
  sense: WordSense | null;
}

export interface WordSense {
  // 뜻마다 다른 태그(자동사·타동사 등) 코드
  tags: string[];
  // JMdict 영어 뜻. 화면에는 보이지 않는다(LLM 입력과 admin에만 쓴다, #97).
  gloss_en: string[];
  // 뜻의 출처와 검수 상태. llm이거나 pending이면 미검수다.
  origin: "jmdict" | "llm";
  status: "pending" | "approved";
  // 한국어 뜻과 그 검수 상태(ai는 검수 전 'AI 번역'). 아직 없으면 null이고, 만들지 못했으면
  // meaning_status가 failed다(#97).
  meaning_ko: string | null;
  meaning_status: "ai" | "reviewed" | "failed";
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
// 함께 싣는다. 서버가 오류 코드(ANALYSIS:USAGE_LIMIT 등, #28)를 보냈으면 그것도 싣는다.
export class AnalysisFailed extends Error {
  constructor(
    readonly translation?: Translation,
    readonly earlyGrammar?: GrammarItem[],
    readonly previous?: Analysis,
    readonly code?: string,
  ) {
    super("분석 실패");
  }
}

// 서버는 줄 단위 JSON으로 translation(번역, 루비) → analysis(번역, 문법, 단어)를 보내고,
// 실패하면 error를 보낸다. LLM 없이 확정한 문법이나 판별 대상 구간, 사전에서 찾은 단어가 있으면
// 그보다 먼저 grammar(확정 문법, 판별 대상 구간, 단어)를 보낸다. 실패(AnalysisFailed)에는 받은
// 확정 문법만 싣고, 판별 대상 구간과 먼저 온 단어는 싣지 않는다(화면에서 지운다). stale 분석이면 맨 먼저 previous(옛 번역, 루비,
// 문법, 단어)를 보내고 onPrevious를 부른다. 이어지는 이벤트는 다시 분석하는 흐름 그대로다.
// 패턴 세트 버전이 올라 다시 매칭한 캐시 문장에 판별 대상 새 구간이 있으면 같은 순서로
// grammar(저장 문법과 새 확정 문법, 새 판별 대상 구간) → translation(저장 번역) → analysis를
// 보낸다. 재판정이 실패해도 error 없이 저장 결과로 analysis를 보낸다(#41).
// 새 문장은 analysis 전에 judged(첫 LLM 응답이 판정한 문법을 더한 문법, 남은 판별 대상 구간, LLM이
// 고른 뜻을 채운 단어)가 올 수 있고, 그때 onJudged를 부른다(#97). 판정은 저장 전이라 실패
// (AnalysisFailed)에는 싣지 않는다.
// grammar가 오면 onEarlyGrammar를, 번역이 오면 onTranslation을 부르고, 다 오면 분석 전체를
// 돌려준다. analysis의 번역은 문법·단어와 짝인 저장된 번역이라 그것을 쓴다.
export async function analyzeSentence(
  text: string,
  onTranslation: (translation: Translation) => void,
  onEarlyGrammar?: (
    grammar: GrammarItem[],
    checking: CheckingItem[],
    words: WordItem[],
  ) => void,
  onPrevious?: (previous: Analysis) => void,
  onJudged?: (
    grammar: GrammarItem[],
    checking: CheckingItem[],
    words: WordItem[],
  ) => void,
): Promise<Analysis> {
  const token = await loadToken();
  if (!token) throw new LoginRequired();
  const response = await fetch(`${API_BASE_URL}/api/analyses/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ text }),
  });
  if (response.status === 401) {
    await clearTokenIfStill(token);
    throw new LoginRequired();
  }
  if (!response.ok || !response.body) {
    throw new AnalysisFailed(
      undefined,
      undefined,
      undefined,
      await errorCode(response),
    );
  }
  let translation: Translation | undefined;
  let earlyGrammar: GrammarItem[] | undefined;
  let previous: Analysis | undefined;
  let code: string | undefined;
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
        onEarlyGrammar?.(earlyGrammar, event.checking, event.words ?? []);
      } else if (event.type === "judged") {
        onJudged?.(event.grammar, event.checking, event.words);
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
        code = event.error;
        break;
      }
    }
  } catch {
    // 연결이 끊기거나 줄이 JSON이 아니어도 이미 받은 번역은 남긴다.
  }
  // error 이벤트를 받았거나, analysis 전에 스트림이 끝났거나 끊겼다.
  throw new AnalysisFailed(translation, earlyGrammar, previous, code);
}

type StreamEvent =
  | ({ type: "previous" } & Analysis)
  | {
      type: "grammar";
      grammar: GrammarItem[];
      checking: CheckingItem[];
      // 새 문장에서 사전으로 찾은 단어(LLM 응답 전). 재매칭의 grammar 이벤트에는 없다.
      words?: WordItem[];
    }
  | ({ type: "translation" } & Translation)
  | {
      type: "judged";
      grammar: GrammarItem[];
      checking: CheckingItem[];
      words: WordItem[];
    }
  | ({ type: "analysis" } & Omit<Analysis, "ruby">)
  | { type: "error"; error: string };

// 오류 응답 본문 {"error": 코드}의 코드. JSON이 아니면 없다.
async function errorCode(response: Response): Promise<string | undefined> {
  try {
    return ((await response.json()) as { error?: string }).error;
  } catch {
    return undefined;
  }
}

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
