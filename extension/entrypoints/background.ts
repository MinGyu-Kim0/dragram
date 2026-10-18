export default defineBackground(() => {
  // 툴바의 확장 아이콘을 누르면 사이드 패널을 연다.
  browser.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
});
