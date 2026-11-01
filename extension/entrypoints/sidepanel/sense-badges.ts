import type { WordSense } from "@/utils/api";

// 뜻의 배지(배지 줄에 둔다). 서버가 준 출처·검수 상태로 정한다. 승인 전 뜻은 'AI 생성·미검수',
// 사전 뜻을 옮긴 검수 전 한국어 뜻은 'AI 번역'이다. 관리자가 승인한 LLM 뜻은 한국어 뜻까지 승인한
// 것이라 배지가 없다. 한국어 뜻이 아직 없으면 없다.
export function senseBadges(sense: WordSense | null) {
  if (sense?.meaning_ko == null) return { pending: false, translated: false };
  const pending = sense.status === "pending";
  return {
    pending,
    translated:
      !pending && sense.origin !== "llm" && sense.meaning_status === "ai",
  };
}
