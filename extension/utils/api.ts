// 개발 빌드 기본값은 로컬 compose 백엔드다. 바꾸려면 빌드할 때 WXT_API_BASE_URL을 준다.
export const API_BASE_URL =
  import.meta.env.WXT_API_BASE_URL ?? "http://localhost:8000";

export interface GrammarItem {
  // 원문(보낸 문장) 기준 UTF-16 위치 [start, end). 자바스크립트 문자열 위치와 같다.
  start: number;
  end: number;
  name: string;
  explanation_ko: string;
  // pending은 LLM이 썼고 아직 검수되지 않은 문법이다.
  review_status: "pending" | "approved";
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

// 분석 실패. 실패 전에 받은 번역과 확정 문법을 함께 싣는다.
export class AnalysisFailed extends Error {
  constructor(
    readonly translation?: Translation,
    readonly grammar?: GrammarItem[],
  ) {
    super("분석 실패");
  }
}

// 서버는 줄 단위 JSON으로 translation(번역, 루비) → analysis(번역, 문법, 단어)를 보내고,
// 실패하면 error를 보낸다. LLM 없이 확정한 문법이 있으면 그보다 먼저 grammar를 보낸다.
// grammar가 오면 onGrammar를, 번역이 오면 onTranslation을 부르고, 다 오면 분석 전체를
// 돌려준다. analysis의 번역은 문법·단어와 짝인 저장된 번역이라 그것을 쓴다.
export async function analyzeSentence(
  text: string,
  onTranslation: (translation: Translation) => void,
  onGrammar?: (grammar: GrammarItem[]) => void,
): Promise<Analysis> {
  const response = await fetch(`${API_BASE_URL}/api/analyses/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok || !response.body) throw new AnalysisFailed();
  let translation: Translation | undefined;
  let grammar: GrammarItem[] | undefined;
  try {
    for await (const event of ndjsonEvents(response.body)) {
      if (event.type === "grammar") {
        grammar = event.grammar;
        onGrammar?.(grammar);
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
  throw new AnalysisFailed(translation, grammar);
}

type StreamEvent =
  | { type: "grammar"; grammar: GrammarItem[] }
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
