// 가이드(#370)를 새 탭으로 연다.
export function openGuide() {
  return browser.tabs.create({ url: browser.runtime.getURL("/guide.html") });
}

// 확장을 처음 설치했을 때만 가이드를 연다. 업데이트 때는 열지 않는다.
export function openGuideOnInstall(reason: string) {
  if (reason === "install") return openGuide();
}
