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

export interface Analysis {
  translation_ko: string;
  grammar: GrammarItem[];
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
