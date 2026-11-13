// 사이드 패널 표시 설정. 사람에 따라 읽기에 방해가 될 수 있는 표시를 끌 수 있게 하고,
// 고른 값을 확장 저장소에 기억한다.

// 원문 한자 위의 루비. 저장한 적이 없으면 켜져 있다.
export async function loadShowRuby(): Promise<boolean> {
  const { showRuby } = await browser.storage.local.get("showRuby");
  return showRuby !== false;
}

export async function saveShowRuby(showRuby: boolean): Promise<void> {
  await browser.storage.local.set({ showRuby });
}

// 원문 형광펜 모양(#354). 고른 적이 없으면 형광펜이다.
export type HighlightStyle = "marker" | "underline";

export async function loadHighlightStyle(): Promise<HighlightStyle> {
  const { highlightStyle } = await browser.storage.local.get("highlightStyle");
  return highlightStyle === "underline" ? "underline" : "marker";
}

export async function saveHighlightStyle(style: HighlightStyle): Promise<void> {
  await browser.storage.local.set({ highlightStyle: style });
}

// 테마(#296). 고른 적이 없으면 null이고 브라우저 설정을 따른다.
export type Theme = "light" | "dark";

export async function loadTheme(): Promise<Theme | null> {
  const { theme } = await browser.storage.local.get("theme");
  return theme === "light" || theme === "dark" ? theme : null;
}

// 고른 테마를 첫 화면 전에 걸고 그린다(#296). 확장 페이지는 인라인 스크립트를 쓸 수 없어
// 저장소를 읽은 뒤 그린다. 읽지 못해도 그린다.
export function renderWithTheme(render: () => void): void {
  loadTheme()
    .then((theme) => {
      if (theme) document.documentElement.dataset.theme = theme;
    })
    .catch(() => {})
    .finally(render);
}

export async function saveTheme(theme: Theme): Promise<void> {
  await browser.storage.local.set({ theme });
}
