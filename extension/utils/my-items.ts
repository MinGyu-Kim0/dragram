import { tokenRequest } from "./token-request";

// 내 일본어 항목(#321): 사용자가 카드에서 추가하거나 '숨김'으로 숨긴 용법·단어 뜻. 본인만
// 보는 개인 데이터다. 예문(원문)은 사용자가 고를 때만 본문으로 보낸다.
// 추가·제외(added)와 숨김·복원(hidden)은 따로 켜고 끈다(#362). 둘 다 꺼지면 항목이 없다.
export type ItemKind = "usage" | "sense";
export interface ItemState {
  added: boolean;
  hidden: boolean;
}

export interface MyItem extends ItemState {
  kind: ItemKind;
  id: number;
  // 저장한 예문이 있는가. 목록(GET)에만 온다.
  has_examples?: boolean;
}

// 웹에서 항목을 바꾼 시각. 열린 패널이 이 값의 변경을 보고 항목을 다시 불러온다.
const CHANGED_KEY = "myItemsChangedAt";

export function markItemsChanged(): Promise<void> {
  return browser.storage.local.set({ [CHANGED_KEY]: Date.now() });
}

export function watchItemsChanged(onChanged: () => void): () => void {
  const listener = (changes: Record<string, unknown>, area: string) => {
    if (area === "local" && CHANGED_KEY in changes) onChanged();
  };
  browser.storage.onChanged.addListener(listener);
  return () => browser.storage.onChanged.removeListener(listener);
}

// 화면이 상태를 찾는 열쇠(종류:ID)
export const itemKey = (kind: ItemKind, id: number) => `${kind}:${id}`;

// '숨김'으로 숨긴 항목인가. ID가 없으면(미확정 문법, 뜻을 고르지 않은 단어) 숨길 수 없다.
export function isHidden(
  states: ReadonlyMap<string, ItemState>,
  kind: ItemKind,
  id: number | null | undefined,
) {
  return id != null && states.get(itemKey(kind, id))?.hidden === true;
}

// 버튼 줄 key에 넣는 상태 글자. 다른 줄에서 상태가 바뀌면 그 줄의 화면 상태도 새로 시작한다.
export const stateTag = (state: ItemState | undefined) =>
  state ? `${state.added}:${state.hidden}` : "none";

export async function fetchMyItems(): Promise<MyItem[]> {
  const response = await tokenRequest("/api/my-items/", "GET");
  return ((await response.json()) as { items: MyItem[] }).items;
}

// 예문으로 저장할 문장과, 그 안에서 카드가 가리키는 부분의 원문 기준 UTF-16 위치 [start, end)
export interface Example {
  text: string;
  start: number;
  end: number;
}

// 준 축만 바꾼다(추가·제외·숨김·복원). example을 주면(추가할 때만) 예문으로 저장한다. 제외하면
// 예문이 지워지고, 두 축이 모두 꺼지면 항목이 없어진다.
export async function saveMyItem(
  kind: ItemKind,
  id: number,
  changes: Partial<ItemState>,
  example?: Example,
): Promise<MyItem> {
  const response = await tokenRequest("/api/my-items/", "PUT", {
    kind,
    id,
    ...changes,
    ...(example !== undefined && {
      example: example.text,
      example_start: example.start,
      example_end: example.end,
    }),
  });
  return (await response.json()) as MyItem;
}
