import { type ReactNode, useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router";
import { request } from "../connect/auth";
import SiteLayout, { CC_BY_SA_URL, JMDICT_URL } from "../site/SiteLayout";
import type { ReviewStatus, WordEntry } from "./analysis";
import { BadgeRow, PendingBadge, WordRow } from "./cards";
import "../connect/connect.css";
import "./history.css";

// 내 기록: 사이드 패널 카드에서 추가하거나 '표시 안 함'으로 숨긴 내 일본어(#321, #324). 문법·단어
// 탭과 추가한·숨긴 항목 필터를 두고, 항목 상태와 사용자가 고른 예문을 여기서 바꾸거나 지운다.
// 분석한 문장 원문은 저장하지 않으므로 문장 목록은 없다.

type Example = { id: number; text: string };

// 반려된 용법·뜻은 내용 없이 예문만 온다. 사용자가 자기 원문을 지울 수 있게 하기 위해서다.
type Rejected = { rejected: true; examples: Example[] };

type Usage = {
  usage_id: number;
  pattern_name: string;
  name: string;
  explanation_ko: string;
  korean_equivalent: string | null;
  korean_equivalent_review_status: ReviewStatus | null;
  review_status: ReviewStatus;
  examples: Example[];
};

type Word = WordEntry & { sense_id: number; examples: Example[] };

type UsageEntry = Usage | (Rejected & { usage_id: number });
type WordListEntry = Word | (Rejected & { sense_id: number });

type Kind = "usage" | "sense";
type ItemState = "added" | "hidden";

const TABS = [
  { key: "grammar", label: "문법" },
  { key: "words", label: "단어" },
] as const;

const FILTERS = [
  { key: "added", label: "추가한 항목" },
  { key: "hidden", label: "숨긴 항목" },
] as const;

type Tab = (typeof TABS)[number]["key"];

const pick = <T extends string>(
  value: string | null,
  options: readonly { key: T }[],
): T => options.find((o) => o.key === value)?.key ?? options[0]!.key;

const usagesOf = (body: { usages: UsageEntry[] }) => body.usages;
const wordsOf = (body: { words: WordListEntry[] }) => body.words;

/** 로그인한 사용자의 내 기록. 홈(/)과 /sentences가 같이 쓴다. 고른 탭과 필터는 주소(?tab=,
 * ?state=)에 남긴다.
 */
export function MyRecords() {
  const [params, setParams] = useSearchParams();
  const tab = pick(params.get("tab"), TABS);
  const state = pick(params.get("state"), FILTERS);
  const go = (next: { tab?: Tab; state?: ItemState }) =>
    setParams(
      { tab: next.tab ?? tab, state: next.state ?? state },
      { replace: true },
    );

  return (
    <div className="connect">
      <section className="card history">
        <h1>내 기록</h1>
        <p className="secondary">
          사이드 패널의 문법·단어 카드에서 추가한 것이 여기에 모여요. 문장
          원문은 예문으로 저장하기로 고른 것만 남아요.
        </p>
        <div role="tablist" className="tabs">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              role="tab"
              id={`tab-${key}`}
              aria-selected={tab === key}
              aria-controls="tab-panel"
              onClick={() => go({ tab: key })}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="filters" role="group" aria-label="보기">
          {FILTERS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              aria-pressed={state === key}
              onClick={() => go({ state: key })}
            >
              {label}
            </button>
          ))}
        </div>
        <div role="tabpanel" id="tab-panel" aria-labelledby={`tab-${tab}`}>
          {tab === "grammar" ? (
            <ItemList<UsageEntry>
              key={`grammar-${state}`}
              url={`/api/my-japanese/grammar/?state=${state}`}
              select={usagesOf}
              name={state === "added" ? "추가한 문법" : "숨긴 문법"}
              empty={
                state === "added"
                  ? "추가한 문법이 아직 없어요. 사이드 패널의 문법 카드에서 '추가'를 눌러 보세요."
                  : "숨긴 문법이 없어요."
              }
              failed="문법을 불러오지 못했어요. 페이지를 새로 고쳐 주세요."
              kind="usage"
              idOf={(u) => u.usage_id}
              state={state}
              render={(usage, index) =>
                "rejected" in usage ? (
                  <p className="muted">
                    검수에서 빠진 문법이에요. 저장한 예문을 지우거나 항목을 뺄
                    수 있어요.
                  </p>
                ) : (
                  <UsageBody usage={usage} index={index} />
                )
              }
            />
          ) : (
            <ItemList<WordListEntry>
              key={`words-${state}`}
              url={`/api/my-japanese/words/?state=${state}`}
              select={wordsOf}
              name={state === "added" ? "추가한 단어" : "숨긴 단어"}
              empty={
                state === "added"
                  ? "추가한 단어가 아직 없어요. 사이드 패널의 단어 카드에서 '추가'를 눌러 보세요."
                  : "숨긴 단어가 없어요."
              }
              failed="단어를 불러오지 못했어요. 페이지를 새로 고쳐 주세요."
              kind="sense"
              idOf={(w) => w.sense_id}
              state={state}
              render={(word) =>
                "rejected" in word ? (
                  <p className="muted">
                    검수에서 빠진 단어 뜻이에요. 저장한 예문을 지우거나 항목을
                    뺄 수 있어요.
                  </p>
                ) : (
                  <WordRow word={word} />
                )
              }
              after={(words) =>
                words.some((w) => !("rejected" in w) && w.in_dictionary) && (
                  <p className="muted">
                    단어 정보: <a href={JMDICT_URL}>JMdict</a> (EDRDG,{" "}
                    <a href={CC_BY_SA_URL}>CC BY-SA 4.0</a>).
                  </p>
                )
              }
            />
          )}
        </div>
      </section>
    </div>
  );
}

type Load<T> =
  { kind: "loading" } | { kind: "failed" } | { kind: "ready"; items: T[] };

/** 탭 하나의 항목 목록. 항목마다 예문과 상태 버튼을 붙이고, 상태가 바뀌어 이 필터에서 빠진 항목은
 * 목록에서 뺀다.
 */
function ItemList<T extends { examples: Example[] }>({
  url,
  select,
  name,
  empty,
  failed,
  kind,
  idOf,
  state,
  render,
  after,
}: {
  url: string;
  select: (body: never) => T[];
  name: string;
  empty: string;
  failed: string;
  kind: Kind;
  idOf: (item: T) => number;
  state: ItemState;
  render: (item: T, index: number) => ReactNode;
  after?: (items: T[]) => ReactNode;
}) {
  const [load, setLoad] = useState<Load<T>>({ kind: "loading" });

  useEffect(() => {
    request<never>("GET", url).then(
      (body) => setLoad({ kind: "ready", items: select(body) }),
      () => setLoad({ kind: "failed" }),
    );
  }, [url, select]);

  if (load.kind === "loading") return <p className="muted">불러오는 중…</p>;
  if (load.kind === "failed")
    return (
      <p role="alert" className="danger">
        {failed}
      </p>
    );
  if (load.items.length === 0) return <p className="secondary">{empty}</p>;
  const update = (id: number, change: (item: T) => T | undefined) =>
    setLoad((current) =>
      current.kind !== "ready"
        ? current
        : {
            ...current,
            items: current.items.flatMap((item) => {
              if (idOf(item) !== id) return [item];
              const next = change(item);
              return next ? [next] : [];
            }),
          },
    );
  return (
    <>
      <ul aria-label={name}>
        {load.items.map((item, index) => {
          const id = idOf(item);
          return (
            <li key={id} className="item-card">
              {render(item, index)}
              <Examples
                examples={item.examples}
                onDeleted={(exampleId) =>
                  update(id, (it) => ({
                    ...it,
                    examples: it.examples.filter((e) => e.id !== exampleId),
                  }))
                }
              />
              <ItemActions
                kind={kind}
                id={id}
                state={state}
                rejected={"rejected" in item}
                hasExamples={item.examples.length > 0}
                onChanged={() => update(id, () => undefined)}
              />
            </li>
          );
        })}
      </ul>
      {after?.(load.items)}
    </>
  );
}

/** 문법 카드 내용. 미검수 표시는 사이드 패널과 같다. */
function UsageBody({ usage, index }: { usage: Usage; index: number }) {
  const pending = usage.review_status === "pending";
  return (
    <>
      <BadgeRow pending={pending} />
      <div className="grammar-card-head">
        <span lang="ja" className={`grammar-chip highlight-${index % 4}`}>
          {usage.pattern_name}
        </span>
        <h2>{usage.name}</h2>
      </div>
      {usage.korean_equivalent !== null && (
        <p>
          {usage.korean_equivalent}
          {!pending && usage.korean_equivalent_review_status === "pending" && (
            <PendingBadge />
          )}
        </p>
      )}
      <p className="secondary">{usage.explanation_ko}</p>
    </>
  );
}

/** 사용자가 고른 예문. 하나씩 지울 수 있다. */
function Examples({
  examples,
  onDeleted,
}: {
  examples: Example[];
  onDeleted: (id: number) => void;
}) {
  const [failed, setFailed] = useState(false);
  if (examples.length === 0) return null;
  return (
    <>
      <ul className="examples" aria-label="내 예문">
        {examples.map((example) => (
          <li key={example.id}>
            <span lang="ja">{example.text}</span>
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setFailed(false);
                request<void>("DELETE", `/api/my-examples/${example.id}/`).then(
                  () => onDeleted(example.id),
                  () => setFailed(true),
                );
              }}
            >
              예문 지우기
            </button>
          </li>
        ))}
      </ul>
      {failed && (
        <p role="alert" className="danger">
          예문을 지우지 못했어요. 다시 시도해 주세요.
        </p>
      )}
    </>
  );
}

/** 항목 상태 버튼. 추가한 항목은 숨기기·빼기, 숨긴 항목은 다시 보이기·추가로 바꾸기. 반려된
 * 항목은 빼기만 있다. 빼면 예문도 지워지므로 예문이 있으면 한 번 확인받는다.
 */
function ItemActions({
  kind,
  id,
  state,
  rejected,
  hasExamples,
  onChanged,
}: {
  kind: Kind;
  id: number;
  state: ItemState;
  rejected: boolean;
  hasExamples: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const send = (method: "PUT" | "DELETE", next?: ItemState) => {
    setBusy(true);
    setFailed(false);
    request<unknown>(method, "/api/my-items/", {
      kind,
      id,
      ...(next && { state: next }),
    }).then(onChanged, () => {
      setFailed(true);
      setBusy(false);
    });
  };
  const remove = () => send("DELETE");
  if (confirming)
    return (
      <div className="actions">
        <p className="secondary">
          빼면 저장한 예문도 함께 지워져요. 되돌릴 수 없어요.
        </p>
        <button
          type="button"
          className="danger-button"
          disabled={busy}
          onClick={remove}
        >
          예문과 함께 빼기
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={busy}
          onClick={() => setConfirming(false)}
        >
          취소
        </button>
        {failed && <Failed />}
      </div>
    );
  const removeButton = (
    <button
      type="button"
      className="secondary-button"
      disabled={busy}
      onClick={() => (hasExamples ? setConfirming(true) : remove())}
    >
      빼기
    </button>
  );
  return (
    <div className="actions">
      {rejected ? (
        removeButton
      ) : state === "added" ? (
        <>
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={() => send("PUT", "hidden")}
          >
            숨기기
          </button>
          {removeButton}
        </>
      ) : (
        <>
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={remove}
          >
            다시 보이기
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={() => send("PUT", "added")}
          >
            추가로 바꾸기
          </button>
        </>
      )}
      {failed && <Failed />}
    </div>
  );
}

function Failed() {
  return (
    <p role="alert" className="danger">
      바꾸지 못했어요. 다시 시도해 주세요.
    </p>
  );
}

function MySentencesPage() {
  return (
    <SiteLayout>
      {/* 로그인 확인이 실패했으면 로그인 화면으로 보내지 않고 목록 요청의 결과(오류)를 보인다. */}
      {(user, failed) =>
        user || failed ? <MyRecords /> : <Navigate to="/connect" replace />
      }
    </SiteLayout>
  );
}

export default MySentencesPage;
