import { useState } from "react";
import {
  itemKey,
  type Example,
  type ItemKind,
  type ItemState,
} from "@/utils/my-items";
import { BadgeRow } from "./BadgeRow";

// 내 일본어 항목(#321): 카드에서 추가하거나 '표시 안 함'으로 숨긴 용법·단어 뜻의 상태와 바꾸는
// 동작. 바꾸는 동작은 실패하면 거부되고, 화면은 성공했을 때만 바뀐다.
export interface MyItems {
  states: ReadonlyMap<string, ItemState>;
  save: (
    kind: ItemKind,
    id: number,
    state: ItemState,
    example?: Example,
  ) => Promise<void>;
  remove: (kind: ItemKind, id: number) => Promise<void>;
}

// 카드 아래 버튼 줄. 부르는 쪽이 key에 상태를 넣어, 같은 항목을 다른 줄에서 빼면 이 줄의
// '예문 저장됨'도 함께 초기화된다(PR #327 리뷰). 추가 전: 추가 · 표시 안 함. 추가한 뒤: 추가됨 표시, 이 문장을 예문으로 저장,
// 빼기(예문도 지운다). 예문은 사용자가 누를 때만 원문 그대로 보낸다.
export function ItemActions({
  kind,
  id,
  example,
  items,
  hideable = true,
}: {
  kind: ItemKind;
  id: number;
  // 예문으로 저장할 문장(이 페이지의 원문)과 그 안에서 이 카드가 가리키는 부분
  example: Example;
  items: MyItems;
  // 구성 문법 하위 박스는 바깥 카드와 함께 보이고 숨으므로 '표시 안 함'을 두지 않는다.
  hideable?: boolean;
}) {
  const state = items.states.get(itemKey(kind, id));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [exampleSaved, setExampleSaved] = useState(false);
  const run = (action: () => Promise<void>, after?: () => void) => {
    setBusy(true);
    setError(false);
    action()
      .then(after, () => setError(true))
      .finally(() => setBusy(false));
  };
  return (
    <>
      <div className="item-actions">
        {state === "added" ? (
          <>
            <span className="item-mark">내 일본어에 추가됨</span>
            {exampleSaved ? (
              <span className="item-mark">예문 저장됨</span>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(
                    () => items.save(kind, id, "added", example),
                    () => setExampleSaved(true),
                  )
                }
              >
                이 문장을 예문으로 저장
              </button>
            )}
            <button
              type="button"
              className="text-button item-remove"
              disabled={busy}
              onClick={() =>
                run(
                  () => items.remove(kind, id),
                  () => setExampleSaved(false),
                )
              }
            >
              빼기
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => run(() => items.save(kind, id, "added"))}
            >
              추가
            </button>
            {hideable && (
              <button
                type="button"
                className="text-button item-remove"
                disabled={busy}
                onClick={() => run(() => items.save(kind, id, "hidden"))}
              >
                표시 안 함
              </button>
            )}
          </>
        )}
      </div>
      {error && (
        <p className="error">저장하지 못했습니다. 다시 시도해 주세요.</p>
      )}
    </>
  );
}

export interface HiddenCard {
  key: string;
  kind: ItemKind;
  id: number;
  // 칩 글자(문법은 패턴, 단어는 사전형)와 이름(용법 이름, 단어 뜻)
  chip: string;
  name: string;
  // 이름에 다는 배지. 카드에서처럼 미검수가 검수처럼 보이지 않게 한다(ADR 0003).
  pending: boolean;
  translated: boolean;
}

// '표시 안 함'으로 숨긴 카드. 접어 두고, 펼치면 칩과 이름, '다시 보이기'만 보인다. 형광펜은 칠하지
// 않는다(원문 형광펜과 카드 칩 색을 맞추기 위해 숨긴 문법은 처음부터 뺀다).
export function HiddenCards({
  cards,
  items,
}: {
  cards: HiddenCard[];
  items: MyItems;
}) {
  if (cards.length === 0) return null;
  return (
    <details className="hidden-cards">
      <summary>숨긴 카드 {cards.length}개</summary>
      <ul aria-label="숨긴 카드">
        {cards.map((card) => (
          <HiddenRow key={card.key} card={card} items={items} />
        ))}
      </ul>
    </details>
  );
}

function HiddenRow({ card, items }: { card: HiddenCard; items: MyItems }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  return (
    <li>
      <BadgeRow pending={card.pending} translated={card.translated} />
      <span lang="ja" className="grammar-chip hidden-chip">
        {card.chip}
      </span>
      <span>{card.name}</span>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError(false);
          items
            .remove(card.kind, card.id)
            .catch(() => setError(true))
            .finally(() => setBusy(false));
        }}
      >
        다시 보이기
      </button>
      {error && <p className="error">바꾸지 못했습니다. 다시 시도해 주세요.</p>}
    </li>
  );
}
