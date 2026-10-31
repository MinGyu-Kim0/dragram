// 사이드 패널 표시 설정. 사람에 따라 읽기에 방해가 될 수 있는 표시를 끌 수 있게 하고,
// 고른 값을 확장 저장소에 기억한다. 저장한 적이 없으면 켜져 있다.
// - showDragHandles: 원문의 드래그 핸들
// - showRuby: 원문 한자 위의 루비
export type Preference = "showDragHandles" | "showRuby";

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

// 테마(#296). 고른 적이 없으면 null이고 브라우저 설정을 따른다.
export type Theme = "light" | "dark";

export async function loadTheme(): Promise<Theme | null> {
  const { theme } = await browser.storage.local.get("theme");
  return theme === "light" || theme === "dark" ? theme : null;
}

export async function saveTheme(theme: Theme): Promise<void> {
  await browser.storage.local.set({ theme });
}
