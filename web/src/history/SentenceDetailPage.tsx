import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router";
import { AuthError, currentUser, request } from "../connect/auth";
import { CC_BY_SA_URL, JMDICT_URL } from "../site/SiteLayout";
import {
  FUNCTION_TAG_NAMES,
  NAME_TYPE_NAMES,
  TAG_NAMES,
  type GrammarItem,
  type NameSpan,
  type RubyItem,
  type SentenceDetail,
  type WordItem,
  type WordSense,
} from "./analysis";
import "../connect/connect.css";
import "./history.css";

// 내 기록의 문장 하나와 저장된 분석(#195). 서버가 저장된 결과만 읽어 주므로 LLM을 부르지 않는다.
// 사이드 패널과 같은 정보를 DESIGN 기준으로 웹에 새로 그린다(컴포넌트 공용화는 하지 않는다).
// shortcut: 같은 용법·같은 단어 카드 합치기(#211)와 원문 형광펜은 그리지 않는다. 필요해지면 더한다.

type State =
  | { kind: "loading" }
  | { kind: "signedOut" }
  | { kind: "problem"; message: string }
  | { kind: "ready"; detail: SentenceDetail };

function problemOf(e: unknown) {
  if (e instanceof AuthError && e.code === "SENTENCE:NOT_FOUND")
    return "이 문장을 찾지 못했어요. 이미 지웠을 수 있어요.";
  if (e instanceof AuthError && e.code === "SENTENCE:OUTDATED")
    return "이 문장의 분석 방식이 바뀌었어요. 확장 프로그램에서 이 문장을 다시 분석하면 볼 수 있어요.";
  if (e instanceof AuthError && e.code === "ANALYSIS:TOO_MANY_REQUESTS")
    return "다른 분석이 진행 중이에요. 잠시 뒤 다시 열어 주세요.";
  return "분석을 불러오지 못했어요. 페이지를 새로 고쳐 주세요.";
}

function SentenceDetailPage() {
  const { id } = useParams();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    // 방문 기록으로 다른 문장에 바로 가면 늦게 온 이전 문장의 결과는 버린다.
    let current = true;
    const show = (next: State) => current && setState(next);
    setState({ kind: "loading" });
    currentUser()
      .then(async (user) => {
        if (!user) return show({ kind: "signedOut" });
        const detail = await request<SentenceDetail>(
          "GET",
          `/api/my-sentences/${id}/`,
        );
        show({ kind: "ready", detail });
      })
      .catch((e) => show({ kind: "problem", message: problemOf(e) }));
    return () => {
      current = false;
    };
  }, [id]);

  if (state.kind === "signedOut") return <Navigate to="/connect" replace />;

  return (
    <main className="connect">
      <section className="card history">
        <Link to="/sentences" className="back-link">
          ← 내 기록
        </Link>
        {state.kind === "loading" && <p className="muted">불러오는 중…</p>}
        {state.kind === "problem" && (
          <p role="alert" className="danger">
            {state.message}
          </p>
        )}
        {state.kind === "ready" && <Detail detail={state.detail} />}
      </section>
    </main>
  );
}

function Detail({ detail }: { detail: SentenceDetail }) {
  const fromDictionary = detail.words.some((w) => w.in_dictionary);
  return (
    <>
      <h1 lang="ja" className="sentence-title">
        <WithRuby text={detail.text} ruby={detail.ruby} />
      </h1>
      <p className="translation">{detail.translation_ko}</p>

      <h2>문법 {detail.grammar.length}</h2>
      {detail.grammar.length === 0 ? (
        <p className="secondary">문법 요소 없음</p>
      ) : (
        <ul className="grammar-cards" aria-label="문법">
          {detail.grammar.map((item, index) => (
            <li
              key={`${item.start}-${item.end}-${index}`}
              className={
                (item.alternatives ?? []).length > 0
                  ? "grammar-card divergent"
                  : "grammar-card"
              }
            >
              <GrammarBody text={detail.text} item={item} index={index} />
              {(item.parts ?? []).length > 0 && (
                <ul className="grammar-parts" aria-label="구성 문법">
                  {item.parts!.map((part, i) => (
                    <li key={i} className="grammar-part">
                      <GrammarBody
                        text={detail.text}
                        item={part}
                        index={index}
                        Heading="h4"
                      />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}

      <h2>단어 {detail.words.length}</h2>
      {detail.words.length === 0 ? (
        <p className="secondary">단어 없음</p>
      ) : (
        <ul className="word-list" aria-label="단어">
          {detail.words.map((w) => (
            <WordRow
              key={`${w.start}-${w.end}`}
              word={w}
              nameSpans={detail.name_spans}
            />
          ))}
        </ul>
      )}
      {fromDictionary && (
        <p className="muted">
          단어 정보: <a href={JMDICT_URL}>JMdict</a> (EDRDG,{" "}
          <a href={CC_BY_SA_URL}>CC BY-SA 4.0</a>). 이 문장에 맞는 뜻만 골라
          보여 줘요.
        </p>
      )}
    </>
  );
}

// 원문에 루비(한자 읽기)를 단다.
function WithRuby({ text, ruby }: { text: string; ruby: RubyItem[] }) {
  const nodes = [];
  let at = 0;
  for (const piece of [...ruby].sort((a, b) => a.start - b.start)) {
    if (piece.start < at) continue;
    nodes.push(text.slice(at, piece.start));
    nodes.push(
      <ruby key={piece.start}>
        {text.slice(piece.start, piece.end)}
        <rt>{piece.reading}</rt>
      </ruby>,
    );
    at = piece.end;
  }
  nodes.push(text.slice(at));
  return <>{nodes}</>;
}

function PendingBadge() {
  return <span className="badge-warn">AI 생성·미검수</span>;
}

// 배지 줄(DESIGN 3장): 상태 배지가 하나도 없으면 줄째로 뺀다.
function BadgeRow({
  pending = false,
  translated = false,
  colloquial = false,
  nameLabel,
}: {
  pending?: boolean;
  translated?: boolean;
  colloquial?: boolean;
  nameLabel?: string;
}) {
  if (!pending && !translated && !colloquial && !nameLabel) return null;
  return (
    <div className="card-badges">
      {pending && <PendingBadge />}
      {translated && <span className="badge-warn">AI 번역</span>}
      {colloquial && <span className="badge-neutral">회화체</span>}
      {nameLabel && <span className="badge-neutral">{nameLabel}</span>}
    </div>
  );
}

// 문법 카드와 하위 박스의 내용. 미검수 표시는 사이드 패널 Grammar.tsx와 같은 규칙이다.
function GrammarBody({
  text,
  item,
  index,
  Heading = "h3",
}: {
  text: string;
  item: GrammarItem;
  index: number;
  Heading?: "h3" | "h4";
}) {
  const pending = item.review_status === "pending";
  const tags = [
    ...item.pos_tags.map((code) => TAG_NAMES[code]),
    ...item.function_tags.map((code) => FUNCTION_TAG_NAMES[code]),
  ].filter((name): name is string => name !== undefined);
  const surface = text.slice(item.start, item.end);
  const connection = item.connection;
  return (
    <>
      <BadgeRow pending={pending} colloquial={item.register === "colloquial"} />
      <div className="grammar-card-head">
        <span lang="ja" className={`grammar-chip highlight-${index % 4}`}>
          {item.pattern_name}
        </span>
        <Heading>{item.name}</Heading>
      </div>
      {surface !== item.pattern_name && (
        <p className="muted">
          문장 속 형태: <span lang="ja">{surface}</span>
        </p>
      )}
      {connection?.text && (
        <p className="muted">
          접속: {connection.text}
          {!pending && connection.review_status === "pending" && (
            <PendingBadge />
          )}
        </p>
      )}
      {tags.length > 0 && (
        <div className="tag-row">
          <ul className="tags" aria-label="태그">
            {tags.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
          {!pending && item.function_tags_review_status === "pending" && (
            <PendingBadge />
          )}
        </div>
      )}
      {item.korean_equivalent !== null && (
        <p>
          {item.korean_equivalent}
          {!pending && item.korean_equivalent_review_status === "pending" && (
            <PendingBadge />
          )}
        </p>
      )}
      {item.variant_of !== null && (
        <p className="secondary">「{item.variant_of}」의 회화체</p>
      )}
      {item.state === "unresolved" ? (
        <p className="muted">판단하지 못함</p>
      ) : (
        <p className="secondary">{item.explanation_ko}</p>
      )}
      {(item.alternatives ?? []).length > 0 && (
        <ul className="alternatives" aria-label="다른 해석">
          {item.alternatives!.map((alternative) => (
            <li key={alternative.name}>
              다른 해석: {alternative.name} — {alternative.translation_ko}
              {alternative.review_status === "pending" && <PendingBadge />}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

// 뜻의 배지(사이드 패널 Words.tsx와 같은 규칙). 승인 전 뜻은 'AI 생성·미검수', 사전 뜻을 옮긴
// 검수 전 한국어 뜻은 'AI 번역'이다. 한국어 뜻이 아직 없으면 배지가 없다.
function senseBadges(sense: WordSense | null) {
  if (sense?.meaning_ko == null) return { pending: false, translated: false };
  const pending = sense.status === "pending";
  return {
    pending,
    translated:
      !pending && sense.origin !== "llm" && sense.meaning_status === "ai",
  };
}

// 단어 자리가 든 이름 구간의 종류 이름(사이드 패널 named-words.ts와 같은 규칙). 구간이 겹치면
// 원문 순서상 앞선 구간이다.
function nameLabel(word: WordItem, nameSpans: NameSpan[] | null | undefined) {
  const span = [...(nameSpans ?? [])]
    .sort((a, b) => a.start - b.start)
    .find((s) => s.start <= word.start && word.end <= s.end);
  // LLM이 경칭까지 이름 구간에 넣어도 접미사 자체는 사람 이름이 아니다.
  if (span?.type === "person" && word.tags.includes("suffix")) return undefined;
  return span && NAME_TYPE_NAMES[span.type];
}

function WordRow({
  word,
  nameSpans,
}: {
  word: WordItem;
  nameSpans: NameSpan[] | null | undefined;
}) {
  const codes = new Set([...word.tags, ...(word.sense?.tags ?? [])]);
  const tags = Object.keys(TAG_NAMES)
    .filter((code) => codes.has(code))
    .map((code) => TAG_NAMES[code]!);
  const sense = word.sense;
  return (
    <li className="word-row">
      <BadgeRow
        {...senseBadges(sense)}
        nameLabel={nameLabel(word, nameSpans)}
      />
      <div className="word-head">
        <h3 lang="ja">{word.dictionary_form}</h3>
        <span lang="ja" className="muted">
          {word.reading}
        </span>
      </div>
      {tags.length > 0 && (
        <ul className="tags" aria-label="태그">
          {tags.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
      )}
      {sense?.meaning_ko != null ? (
        <p>{sense.meaning_ko}</p>
      ) : sense?.meaning_status === "failed" ? (
        <p className="muted">뜻을 만들지 못했어요</p>
      ) : word.is_name ? (
        word.reading_ko && <p aria-label="한글 읽기">{word.reading_ko}</p>
      ) : (
        <p className="muted">뜻을 아직 고르지 않았어요</p>
      )}
    </li>
  );
}

export default SentenceDetailPage;
