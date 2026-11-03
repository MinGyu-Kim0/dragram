import { useState } from "react";
import {
  isAdded,
  itemKey,
  type Example,
  type ItemKind,
  type ItemState,
} from "@/utils/my-items";
import { BadgeRow } from "./BadgeRow";

// 내 일본어 항목(#321): 카드에서 추가하거나 '숨김'으로 숨긴 용법·단어 뜻의 상태와 바꾸는
// 동작. 바꾸는 동작은 실패하면 거부되고, 화면은 성공했을 때만 바뀐다.
export interface MyItems {
  states: ReadonlyMap<string, ItemState>;
  // 저장한 예문이 있는 항목의 열쇠. 제외는 예문도 지우므로 한 번 확인받는다.
  withExamples: ReadonlySet<string>;
  // 준 축만 바꾼다(추가·제외·숨김·복원, #362).
  save: (
    kind: ItemKind,
    id: number,
    changes: Partial<ItemState>,
    example?: Example,
  ) => Promise<void>;
}

// 카드 아래 버튼 줄. 부르는 쪽이 key에 상태를 넣어, 같은 항목을 다른 줄에서 바꾸면 이 줄의
// '예문 저장됨'도 함께 초기화된다(PR #327 리뷰). 추가 전: 추가 · 숨김. 추가한 뒤: 추가됨 · 예문 저장 ·
// 숨김. '추가'와 '추가됨'은 한 토글 버튼이라 추가됨을 다시 누르면 제외한다(예문이 있으면 확인,
// #362). 숨김은 숨긴 카드로 보내고 추가·예문은 그대로 둔다. 예문은 사용자가 누를 때만 원문 그대로
// 보낸다.
export function ItemActions({
  kind,
  id,
  example,
  items,
}: {
  kind: ItemKind;
  id: number;
  // 예문으로 저장할 문장(이 페이지의 원문)과 그 안에서 이 카드가 가리키는 부분
  example: Example;
  items: MyItems;
}) {
  const added = isAdded(items.states, kind, id);
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
        {added ? (
          <AddedToggle
            confirm={items.withExamples.has(itemKey(kind, id))}
            busy={busy}
            onExclude={() =>
              run(
                () => items.save(kind, id, { added: false }),
                () => setExampleSaved(false),
              )
            }
          />
        ) : (
          <button
            type="button"
            className="item-toggle"
            aria-pressed={false}
            disabled={busy}
            onClick={() => run(() => items.save(kind, id, { added: true }))}
          >
            추가
          </button>
        )}
        {added &&
          (exampleSaved ? (
            <span className="item-mark">예문 저장됨</span>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                run(
                  () => items.save(kind, id, { added: true }, example),
                  () => setExampleSaved(true),
                )
              }
            >
              예문 저장
            </button>
          ))}
        <button
          type="button"
          className="text-button item-remove"
          disabled={busy}
          onClick={() => run(() => items.save(kind, id, { hidden: true }))}
        >
          숨김
        </button>
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
  // 내 일본어에 추가한 항목인가. 복원하면 추가됨으로 돌아온다(#362).
  added: boolean;
}

// '숨김'으로 숨긴 카드. 접어 두고, 펼치면 칩과 이름, 추가한 항목이면 '추가됨', '복원'만 보인다.
// 형광펜은 칠하지 않는다(원문 형광펜과 카드 칩 색을 맞추기 위해 숨긴 문법은 처음부터 뺀다).
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

// 복원은 숨김만 풀어 지워지는 것이 없으므로 확인 없이 바로 한다(#362).
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
      {card.added && <span className="item-mark">추가됨</span>}
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError(false);
          items
            .save(card.kind, card.id, { hidden: false })
            .catch(() => setError(true))
            .finally(() => setBusy(false));
        }}
      >
        복원
      </button>
      {error && <p className="error">바꾸지 못했습니다. 다시 시도해 주세요.</p>}
    </li>
  );
}

// '추가됨' 토글(#362). 누르면 제외하고, 저장한 예문이 있으면(confirm) 예문도 함께 지워짐을 한 번
// 확인받는다(웹과 같다, PR #320 리뷰).
function AddedToggle({
  confirm,
  busy,
  onExclude,
}: {
  confirm: boolean;
  busy: boolean;
  onExclude: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  if (confirming)
    return (
      <span className="remove-confirm">
        <span>저장한 예문도 함께 지워져요. 되돌릴 수 없어요.</span>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setConfirming(false);
            onExclude();
          }}
        >
          예문과 함께 제외
        </button>
        <button
          type="button"
          className="text-button"
          onClick={() => setConfirming(false)}
        >
          취소
        </button>
      </span>
    );
  return (
    <button
      type="button"
      className="item-toggle"
      aria-pressed
      title="다시 누르면 내 일본어에서 제외해요"
      disabled={busy}
      onClick={() => (confirm ? setConfirming(true) : onExclude())}
    >
      추가됨
    </button>
  );
}
