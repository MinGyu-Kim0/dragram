import { extractSentences } from "@/utils/extract-sentences";

// 우클릭 메뉴를 누를 때 그 탭에 한 번 주입되는 스크립트(utils/page-sentences.ts).
// main이 돌려준 값이 scripting.executeScript의 결과가 된다.
export default defineUnlistedScript(() => {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return [];
  return extractSentences(selection.getRangeAt(0));
});
