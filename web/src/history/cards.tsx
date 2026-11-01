import type { ReactNode } from "react";
import { TAG_NAMES, type WordEntry, type WordSense } from "./analysis";

// 내 기록 카드가 함께 쓰는 배지·단어 행. 미검수 표시는 사이드 패널과 같은 규칙이다(ADR 0003).

export function PendingBadge() {
  return <span className="badge-warn">AI 생성·미검수</span>;
}

// 배지 줄(DESIGN 3장): 상태 배지가 하나도 없으면 줄째로 뺀다.
export function BadgeRow({
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

// 단어 행: 표제·읽기, 태그, 고른 뜻. children(버튼, 예문)은 맨 아래에 붙인다.
export function WordRow({
  word,
  children,
}: {
  word: WordEntry;
  children?: ReactNode;
}) {
  const codes = new Set([...word.tags, ...(word.sense?.tags ?? [])]);
  const tags = Object.keys(TAG_NAMES)
    .filter((code) => codes.has(code))
    .map((code) => TAG_NAMES[code]!);
  const sense = word.sense;
  return (
    <li className="word-row">
      <BadgeRow {...senseBadges(sense)} />
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
      ) : (
        <p className="muted">뜻을 아직 고르지 않았어요</p>
      )}
      {children}
    </li>
  );
}
