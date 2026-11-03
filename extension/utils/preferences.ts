// 사이드 패널 표시 설정. 사람에 따라 읽기에 방해가 될 수 있는 표시를 끌 수 있게 하고,
// 고른 값을 확장 저장소에 기억한다. 저장한 적이 없으면 켜져 있다.
// - showRuby: 원문 한자 위의 루비
export type Preference = "showRuby";

export async function loadPreference(key: Preference): Promise<boolean> {
  const stored = await browser.storage.local.get(key);
  return stored[key] !== false;
}

export async function savePreference(
  key: Preference,
  value: boolean,
): Promise<void> {
  await browser.storage.local.set({ [key]: value });
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

export async function saveTheme(theme: Theme): Promise<void> {
  await browser.storage.local.set({ theme });
}

// 도움말(#365)을 한 번 닫았는가. 닫은 적이 없으면 로그인한 패널에서 한 번 저절로 연다.
export async function loadHelpSeen(): Promise<boolean> {
  const { helpSeen } = await browser.storage.local.get("helpSeen");
  return helpSeen === true;
}

export async function saveHelpSeen(): Promise<void> {
  await browser.storage.local.set({ helpSeen: true });
}
