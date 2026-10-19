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

export interface Analysis {
  translation_ko: string;
  grammar: GrammarItem[];
  words: WordItem[];
}

export async function analyzeSentence(text: string): Promise<Analysis> {
  const response = await fetch(`${API_BASE_URL}/api/analyses/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) throw new Error(`분석 API 오류: ${response.status}`);
  return response.json();
}
