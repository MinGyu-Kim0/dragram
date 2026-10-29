import type { ExtractedSentence } from "./extract-sentences";

// 우클릭한 탭(과 프레임)에 문장 추출 스크립트를 한 번 주입해 문장 목록을 받는다.
// 주입할 수 없는 페이지(크롬 내부 페이지, PDF 뷰어 등)이거나 문장을 찾지 못하면, 메뉴가
// 넘겨준 고른 글자를 그대로 문장 하나로 쓴다.
export async function sentencesFromPage(
  tabId: number,
  frameId: number,
  selectionText: string,
): Promise<ExtractedSentence[]> {
  try {
    const [injection] = await browser.scripting.executeScript({
      target: { tabId, frameIds: [frameId] },
      files: ["/extract-sentences.js"],
    });
    const sentences = injection?.result as ExtractedSentence[] | undefined;
    if (sentences && sentences.length > 0) return sentences;
  } catch {
    // 아래의 고른 글자로 대신한다.
  }
  return [
    { text: selectionText, selection: { start: 0, end: selectionText.length } },
  ];
}
