import { openGuide } from "@/utils/guide";

// 헤더 가이드 버튼(#370). 가이드를 새 탭으로 연다.
export function GuideButton() {
  return (
    <button
      type="button"
      className="theme-button guide-button"
      aria-label="가이드"
      onClick={() => openGuide()}
    >
      ?
    </button>
  );
}
