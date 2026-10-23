import { requestAnalysis } from "@/utils/analysis-request";
import { handleExternalMessage } from "@/utils/external-messages";
import { latestPerKey } from "@/utils/latest";
import { sentencesFromPage } from "@/utils/page-sentences";

const ANALYZE_MENU_ID = "analyze-selection";

export default defineBackground(() => {
  // 같은 창에서 연달아 분석하면, 늦게 끝난 이전 추출이 최신 선택을 덮어쓰지 않게 한다.
  const startExtraction = latestPerKey();

  // 툴바의 확장 아이콘을 누르면 사이드 패널을 연다.
  browser.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

  // 웹 '로그인·확장 연결' 화면이 토큰을 넘기거나(연결) 지우라고(웹 로그아웃) 알린다.
  // 우리 웹이 아닌 출처의 메시지에는 답하지 않는다.
  browser.runtime.onMessageExternal.addListener(
    (message, sender, sendResponse) => {
      const reply = handleExternalMessage(message, sender.url);
      if (!reply) return false;
      reply.then(sendResponse);
      // 답을 비동기로 보내므로 채널을 열어 둔다.
      return true;
    },
  );

  browser.runtime.onInstalled.addListener(() => {
    browser.contextMenus.create({
      id: ANALYZE_MENU_ID,
      title: "Dragram으로 분석",
      contexts: ["selection"],
    });
  });

  browser.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId !== ANALYZE_MENU_ID || !info.selectionText) return;
    if (tab?.windowId === undefined || tab.id === undefined) return;
    // 크롬은 사용자 동작 안에서만 패널을 열 수 있으므로 다른 비동기 작업보다 먼저 연다.
    browser.sidePanel.open({ windowId: tab.windowId });
    // 고른 범위를 문장으로 넓히고 루비 읽기를 뺀 문장 목록을 패널에 넘긴다(#16).
    const windowId = tab.windowId;
    const isLatest = startExtraction(windowId);
    sentencesFromPage(tab.id, info.frameId ?? 0, info.selectionText).then(
      (sentences) => {
        if (isLatest()) requestAnalysis(windowId, sentences);
      },
    );
  });
});
