import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchMyItems,
  itemKey,
  saveMyItem,
  watchItemsChanged,
  type Example,
  type ItemKind,
  type ItemState,
} from "@/utils/my-items";
import type { MyItems } from "./MyItems";
import type { LoginGeneration } from "./use-login-generation";

// 내 일본어 항목 상태(#321, 종류:ID → 추가·숨김). 지정한 이름처럼 연결되면 받고 로그인 세대로 거른다.
export function useMyItemStates(
  connected: boolean | undefined,
  generation: LoginGeneration,
) {
  const [states, setStates] = useState<ReadonlyMap<string, ItemState>>(
    new Map(),
  );
  // 저장한 예문이 있는 항목의 열쇠. 목록을 받거나 예문을 저장·항목을 빼면 바뀐다.
  const [examples, setExamples] = useState<ReadonlySet<string>>(new Set());
  // 웹에서 항목을 바꿀 때마다 올라간다. 올라가면 항목을 다시 불러온다.
  const [changed, setChanged] = useState(0);
  useEffect(
    () => watchItemsChanged(() => setChanged((count) => count + 1)),
    [],
  );
  const edits = useRef(0);
  const queues = useRef(new Map<string, Promise<unknown>>());

  useEffect(() => {
    if (!connected) return;
    let active = true;
    const load = () => {
      const seen = edits.current;
      fetchMyItems().then(
        (loaded) => {
          if (!active) return;
          if (edits.current !== seen) load();
          else {
            setStates(
              new Map(
                loaded.map((item) => [
                  itemKey(item.kind, item.id),
                  { added: item.added, hidden: item.hidden },
                ]),
              ),
            );
            setExamples(
              new Set(
                loaded
                  .filter((item) => item.has_examples)
                  .map((item) => itemKey(item.kind, item.id)),
              ),
            );
          }
        },
        // 받지 못하면 숨긴 카드 없이 보인다.
        () => {},
      );
    };
    load();
    return () => {
      active = false;
    };
  }, [connected, generation.value, changed]);

  // 같은 항목의 바꾸기 요청은 앞 요청이 끝난 뒤 보낸다. 같은 뜻이 여러 줄에 있을 때 응답이 뒤바뀌어
  // 화면이 서버와 어긋나지 않게 한다. 기다리는 사이 로그아웃(계정 변경)했으면 보내지 않는다. 그
  // 요청이 다음 계정의 토큰으로 나가지 않게 하기 위해서다(PR #327 리뷰).
  const inOrder = (key: string, task: () => Promise<void>): Promise<void> => {
    const started = generation.ref.current;
    const previous = queues.current.get(key) ?? Promise.resolve();
    const next = previous
      .catch(() => {})
      .then(() => (generation.ref.current === started ? task() : undefined));
    queues.current.set(key, next);
    return next;
  };
  const items: MyItems = {
    states,
    withExamples: examples,
    save: (
      kind: ItemKind,
      id: number,
      changes: Partial<ItemState>,
      example?: Example,
    ) =>
      inOrder(itemKey(kind, id), async () => {
        const started = generation.ref.current;
        const { added, hidden } = await saveMyItem(kind, id, changes, example);
        if (generation.ref.current !== started) return;
        edits.current += 1;
        const key = itemKey(kind, id);
        // 두 축이 모두 꺼지면 항목이 없어지고, 제외하면 예문도 지워진다.
        setStates((current) => {
          const next = new Map(current);
          if (added || hidden) next.set(key, { added, hidden });
          else next.delete(key);
          return next;
        });
        setExamples((current) => {
          const next = new Set(current);
          if (!added) next.delete(key);
          else if (example) next.add(key);
          return next;
        });
      }),
  };
  const clear = useCallback(() => {
    setStates(new Map());
    setExamples(new Set());
  }, []);

  return { items, clear };
}
