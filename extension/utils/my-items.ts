import { tokenRequest } from "./token-request";

// 내 일본어 항목(#321): 사용자가 카드에서 추가하거나 '표시 안 함'으로 숨긴 용법·단어 뜻. 본인만
// 보는 개인 데이터다. 예문(원문)은 사용자가 고를 때만 본문으로 보낸다.
export type ItemKind = "usage" | "sense";
export type ItemState = "added" | "hidden";

export interface MyItem {
  kind: ItemKind;
  id: number;
  state: ItemState;
}

// 화면이 상태를 찾는 열쇠(종류:ID)
export const itemKey = (kind: ItemKind, id: number) => `${kind}:${id}`;

// '표시 안 함'으로 숨긴 항목인가. ID가 없으면(미확정 문법, 뜻을 고르지 않은 단어) 숨길 수 없다.
export function isHidden(
  states: ReadonlyMap<string, ItemState>,
  kind: ItemKind,
  id: number | null | undefined,
) {
  return id != null && states.get(itemKey(kind, id)) === "hidden";
}

export async function fetchMyItems(): Promise<MyItem[]> {
  const response = await tokenRequest("/api/my-items/", "GET");
  return ((await response.json()) as { items: MyItem[] }).items;
}

// 추가하거나 숨긴다. 같은 항목이면 상태만 바뀐다. example을 주면(추가할 때만) 예문으로 저장한다.
export async function saveMyItem(
  kind: ItemKind,
  id: number,
  state: ItemState,
  example?: string,
): Promise<MyItem> {
  const response = await tokenRequest("/api/my-items/", "PUT", {
    kind,
    id,
    state,
    ...(example !== undefined && { example }),
  });
  return (await response.json()) as MyItem;
}

// 해제한다(추가·숨김을 모두 없앤다). 그 항목의 예문도 지워진다.
export async function removeMyItem(kind: ItemKind, id: number): Promise<void> {
  await tokenRequest("/api/my-items/", "DELETE", { kind, id });
}
