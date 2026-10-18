// 개발 빌드 기본값은 로컬 compose 백엔드다. 바꾸려면 빌드할 때 WXT_API_BASE_URL을 준다.
export const API_BASE_URL =
  import.meta.env.WXT_API_BASE_URL ?? "http://localhost:8000";

export interface Analysis {
  translation_ko: string;
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
