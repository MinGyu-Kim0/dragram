// 원문의 드래그 핸들을 보일지. 사람에 따라 읽기에 방해가 될 수 있어 끌 수 있게 하고,
// 고른 값을 확장 저장소에 기억한다. 저장한 적이 없으면 보인다.
const KEY = "showDragHandles";

export async function loadShowDragHandles(): Promise<boolean> {
  const stored = await browser.storage.local.get(KEY);
  return stored[KEY] !== false;
}

export async function saveShowDragHandles(show: boolean): Promise<void> {
  await browser.storage.local.set({ [KEY]: show });
}
