import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router";
import { AuthError, request } from "../connect/auth";
import SiteLayout from "../site/SiteLayout";
import "../connect/connect.css";
import "./history.css";

// 내 기록: 내가 분석한 문장 목록(#195)과 문장별 삭제(#196). 문장을 누르면 저장된 분석을 본다.

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

/** 로그인한 사용자의 문장 목록. 홈(/)과 /sentences가 같이 쓴다. */
export function SentenceList() {
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
        {state.kind === "loading" && <p className="muted">불러오는 중…</p>}
        {state.kind === "failed" && (
          <p role="alert" className="danger">
            기록을 불러오지 못했어요. 페이지를 새로 고쳐 주세요.
          </p>
        )}
        {state.kind === "ready" &&
          (state.sentences.length === 0 ? (
            <p className="secondary">아직 분석한 문장이 없어요.</p>
          ) : (
            <ul aria-label="분석한 문장">
              {state.sentences.map((s) => (
                <SentenceRow
                  key={s.id}
                  sentence={s}
                  onDeleted={() => removed(s.id)}
                />
              ))}
            </ul>
          ))}
      </section>
    </div>
  );
}

function MySentencesPage() {
  return (
    <SiteLayout>
      {(user) => (user ? <SentenceList /> : <Navigate to="/connect" replace />)}
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
