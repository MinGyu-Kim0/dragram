import { type ReactNode, useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { AuthError, request } from "../connect/auth";
import SiteLayout, { CC_BY_SA_URL, JMDICT_URL } from "../site/SiteLayout";
import type { ReviewStatus, WordItem } from "./analysis";
import { BadgeRow, PendingBadge, WordRow } from "./SentenceDetailPage";
import "../connect/connect.css";
import "./history.css";

// 내 기록: 내가 분석한 문장 목록(#195)과 문장별 삭제(#196), 내 일본어 문법(#313)·단어(#314). 문장을 누르면 저장된
// 분석을 본다.

type Sentence = { id: number; text: string; analyzed_at: string };

type State =
  | { kind: "loading" }
  | { kind: "failed" }
  | { kind: "ready"; sentences: Sentence[] };

const fetchSentences = () =>
  request<{ sentences: Sentence[] }>("GET", "/api/my-sentences/").then(
    (body) => body.sentences,
  );

const deleteSentence = (id: number) =>
  request<void>("DELETE", `/api/my-sentences/${id}/`);

const analyzedAt = (iso: string) =>
  new Date(iso).toLocaleString("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  });

const TABS = [
  { key: "sentences", label: "문장" },
  { key: "grammar", label: "문법" },
  { key: "words", label: "단어" },
] as const;

type Tab = (typeof TABS)[number]["key"];

/** 로그인한 사용자의 내 기록(문장·문법·단어 탭, #313). 홈(/)과 /sentences가 같이 쓴다. 고른
 * 탭은 주소(?tab=)에 남겨 분석 화면에서 뒤로 와도 그 탭을 연다.
 */
export function MyRecords() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.some((t) => t.key === params.get("tab"))
    ? (params.get("tab") as Tab)
    : "sentences";
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    fetchSentences().then(
      (sentences) => setState({ kind: "ready", sentences }),
      () => setState({ kind: "failed" }),
    );
  }, []);

  const removed = (id: number) =>
    setState((s) =>
      s.kind === "ready"
        ? { ...s, sentences: s.sentences.filter((x) => x.id !== id) }
        : s,
    );

  return (
    <div className="connect">
      <section className="card history">
        <h1>내 기록</h1>
        <div role="tablist" className="tabs">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              role="tab"
              id={`tab-${key}`}
              aria-selected={tab === key}
              aria-controls="tab-panel"
              onClick={() =>
                setParams(key === "sentences" ? {} : { tab: key }, {
                  replace: true,
                })
              }
            >
              {key === "sentences" && state.kind === "ready"
                ? `${label} ${state.sentences.length}`
                : label}
            </button>
          ))}
        </div>
        <div role="tabpanel" id="tab-panel" aria-labelledby={`tab-${tab}`}>
          {tab === "sentences" && (
            <SentenceTab state={state} onDeleted={removed} />
          )}
          {tab === "grammar" && (
            <MyJapaneseTab<Usage>
              url="/api/my-japanese/grammar/"
              field="usages"
              name="문법"
              render={(usage, index) => (
                <UsageCard key={usage.usage_id} usage={usage} index={index} />
              )}
            />
          )}
          {tab === "words" && (
            <MyJapaneseTab<MyWord>
              url="/api/my-japanese/words/"
              field="words"
              name="단어"
              render={(word) => (
                <WordRow key={word.sense_id} word={word}>
                  <UsedIn sentences={word.sentences} />
                </WordRow>
              )}
              after={(words) =>
                words.some((w) => w.in_dictionary) && (
                  <p className="muted">
                    단어 정보: <a href={JMDICT_URL}>JMdict</a> (EDRDG,{" "}
                    <a href={CC_BY_SA_URL}>CC BY-SA 4.0</a>). 내 문장에서 고른
                    뜻만 모아 보여 줘요.
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

function SentenceTab({
  state,
  onDeleted,
}: {
  state: State;
  onDeleted: (id: number) => void;
}) {
  if (state.kind === "loading") return <p className="muted">불러오는 중…</p>;
  if (state.kind === "failed")
    return (
      <p role="alert" className="danger">
        기록을 불러오지 못했어요. 페이지를 새로 고쳐 주세요.
      </p>
    );
  if (state.sentences.length === 0)
    return <p className="secondary">아직 분석한 문장이 없어요.</p>;
  return (
    <ul aria-label="분석한 문장">
      {state.sentences.map((s) => (
        <SentenceRow
          key={s.id}
          sentence={s}
          onDeleted={() => onDeleted(s.id)}
        />
      ))}
    </ul>
  );
}

type SentenceLink = { id: number; text: string };

type Usage = {
  usage_id: number;
  pattern_name: string;
  name: string;
  explanation_ko: string;
  korean_equivalent: string | null;
  korean_equivalent_review_status: ReviewStatus | null;
  review_status: ReviewStatus;
  sentences: SentenceLink[];
};

type MyWord = Omit<WordItem, "start" | "end"> & {
  sense_id: number;
  sentences: SentenceLink[];
};

type Load<T> =
  { kind: "loading" } | { kind: "failed" } | { kind: "ready"; items: T[] };

/** 내 일본어 탭 하나(FR-M10). 탭을 열 때 불러오고, 불러오는 중·실패·빈 목록을 보인다. */
function MyJapaneseTab<T>({
  url,
  field,
  name,
  render,
  after,
}: {
  url: string;
  field: string;
  name: string;
  render: (item: T, index: number) => ReactNode;
  after?: (items: T[]) => ReactNode;
}) {
  const [state, setState] = useState<Load<T>>({ kind: "loading" });

  useEffect(() => {
    request<Record<string, T[]>>("GET", url).then(
      (body) => setState({ kind: "ready", items: body[field] }),
      () => setState({ kind: "failed" }),
    );
  }, [url, field]);

  if (state.kind === "loading") return <p className="muted">불러오는 중…</p>;
  if (state.kind === "failed")
    return (
      <p role="alert" className="danger">
        {name}
        {particle(name, "을", "를")} 불러오지 못했어요. 페이지를 새로 고쳐
        주세요.
      </p>
    );
  if (state.items.length === 0)
    return (
      <p className="secondary">
        분석한 문장에 나온 {name}
        {particle(name, "이", "가")} 아직 없어요.
      </p>
    );
  return (
    <>
      <ul aria-label={`내 ${name}`}>{state.items.map(render)}</ul>
      {after?.(state.items)}
    </>
  );
}

// 받침이 있으면 앞 조사, 없으면 뒤 조사
const particle = (word: string, final: string, open: string) =>
  (word.charCodeAt(word.length - 1) - 0xac00) % 28 === 0 ? open : final;

/** 그 항목이 나온 내 문장 링크(접어 둔다) */
function UsedIn({ sentences }: { sentences: SentenceLink[] }) {
  return (
    <details>
      <summary className="muted">문장 {sentences.length}개</summary>
      <ul className="usage-sentences">
        {sentences.map((s) => (
          <li key={s.id} lang="ja">
            <Link to={`/sentences/${s.id}`} className="sentence-link">
              {s.text}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** 문법 카드. 미검수 표시는 문장 분석 화면과 같다. */
function UsageCard({ usage, index }: { usage: Usage; index: number }) {
  const pending = usage.review_status === "pending";
  return (
    <li className="grammar-card">
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
      <UsedIn sentences={usage.sentences} />
    </li>
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

function SentenceRow({
  sentence,
  onDeleted,
}: {
  sentence: Sentence;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const remove = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await deleteSentence(sentence.id);
    } catch (e) {
      // 404면 다른 탭에서 이미 지웠다. 목록에서도 뺀다.
      if (!(e instanceof AuthError && e.status === 404)) {
        setFailed(true);
        setBusy(false);
        return;
      }
    }
    onDeleted();
  };

  return (
    <li>
      <p lang="ja" className="sentence">
        <Link to={`/sentences/${sentence.id}`} className="sentence-link">
          {sentence.text}
        </Link>
      </p>
      <p className="muted">
        <time dateTime={sentence.analyzed_at}>
          {analyzedAt(sentence.analyzed_at)}
        </time>{" "}
        분석
      </p>
      {failed && (
        <p role="alert" className="danger">
          지우지 못했어요. 다시 시도해 주세요.
        </p>
      )}
      {confirming ? (
        <>
          <p className="secondary">
            이 문장을 지울까요? 지운 원문은 되돌릴 수 없어요. 원문 없는 공용
            분석(번역·문법)은 남아요.
          </p>
          <div className="actions">
            <button
              type="button"
              className="danger-button"
              disabled={busy}
              onClick={remove}
            >
              이 문장 지우기
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={busy}
              onClick={() => {
                setFailed(false);
                setConfirming(false);
              }}
            >
              취소
            </button>
          </div>
        </>
      ) : (
        <button
          type="button"
          className="secondary-button"
          onClick={() => setConfirming(true)}
        >
          지우기
        </button>
      )}
    </li>
  );
}

export default MySentencesPage;
