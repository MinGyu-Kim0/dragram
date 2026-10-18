import { requestAnalysis } from "@/utils/analysis-request";

const ANALYZE_MENU_ID = "analyze-selection";

export default defineBackground(() => {
  // 툴바의 확장 아이콘을 누르면 사이드 패널을 연다.
  browser.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

  browser.runtime.onInstalled.addListener(() => {
    browser.contextMenus.create({
      id: ANALYZE_MENU_ID,
      title: "Dragram으로 분석",
      contexts: ["selection"],
    });
  });

  browser.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId !== ANALYZE_MENU_ID || !info.selectionText) return;
    if (tab?.windowId === undefined) return;
    // 크롬은 사용자 동작 안에서만 패널을 열 수 있으므로 다른 비동기 작업보다 먼저 연다.
    browser.sidePanel.open({ windowId: tab.windowId });
    requestAnalysis(info.selectionText);
  });
});
