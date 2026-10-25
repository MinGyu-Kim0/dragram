import { useState } from "react";
import type { RubyItem, WordItem, WordSense } from "@/utils/api";
import { isKana, toHiragana } from "@/utils/names";
import { BadgeRow } from "./BadgeRow";
import { namedWords, wordKey } from "./named-words";
import { draggedFirst, type DragRange } from "./drag-range";
import { TAG_NAMES } from "./tag-names";

// 동사 그룹이 품사 바로 뒤에 오도록 화면 순서를 정한다.
const TAG_ORDER = Object.keys(TAG_NAMES);

// 단어 전체 태그와 고른 뜻의 태그 가운데 화면 이름이 있는 것(TAG_NAMES 순서)
function tagNames(word: WordItem) {
  const codes = new Set([...word.tags, ...(word.sense?.tags ?? [])]);
  return TAG_ORDER.filter((code) => codes.has(code)).map(
    (code) => TAG_NAMES[code]!,
  );
}

// 뜻의 배지(배지 줄에 둔다). 서버가 준 출처·검수 상태로 정한다. 승인 전 뜻은 'AI 생성·미검수',
// 사전 뜻을 옮긴 검수 전 한국어 뜻은 'AI 번역'이다. 관리자가 승인한 LLM 뜻은 한국어 뜻까지 승인한
// 것이라 배지가 없다. 한국어 뜻이 아직 없으면 없다.
function senseBadges(sense: WordSense | null) {
  if (sense?.meaning_ko == null) return { pending: false, translated: false };
  const pending = sense.status === "pending";
  return {
    pending,
    translated:
      !pending && sense.origin !== "llm" && sense.meaning_status === "ai",
  };
}

// 뜻 한 줄: 한국어 뜻을 보인다. 영어 뜻은 보이지 않는다. 한국어 뜻이 아직 없으면 준비 중, 만들지
// 못했으면 실패 문구다(#97).
function Meaning({ sense }: { sense: WordSense }) {
  if (sense.meaning_ko === null) {
    return sense.meaning_status === "failed" ? (
      <p className="word-meaning word-choosing">뜻을 만들지 못했습니다</p>
    ) : (
      <Preparing />
    );
  }
  return <p className="word-meaning">{sense.meaning_ko}</p>;
}

function Preparing() {
  return (
    <p
      role="status"
      aria-label="뜻을 준비하는 중"
      className="word-meaning word-choosing"
    >
      뜻을 준비하는 중
    </p>
  );
}

// 그 자리의 SudachiPy 읽기(히라가나). 루비가 덮은 한자는 루비 읽기로, 나머지 가나는 그대로 읽는다.
// 루비도 가나도 아닌 글자가 있으면 빈 값이다.
function sudachiReading(text: string, word: WordItem, ruby: RubyItem[]) {
  let reading = "";
  for (let at = word.start; at < word.end;) {
    const piece = ruby.find((r) => r.start === at && r.end <= word.end);
    if (piece) {
      reading += piece.reading;
      at = piece.end;
    } else {
      reading += toHiragana(text[at]!);
      at += 1;
    }
  }
  return isKana(reading) ? reading : "";
}

export interface NameActions {
  // 실패하면 거부된다. 화면은 성공했을 때만 바뀐다.
  onSave: (surface: string, reading: string) => Promise<void>;
  onRemove: (surface: string) => Promise<void>;
}

// 읽기 입력(이름으로 지정, 읽기 고치기). 사전 읽기는 칩으로 탭 한 번에 고른다. 가나만 받는다.
function NameEditor({
  initial,
  chips,
  onSave,
  onCancel,
}: {
  initial: string;
  chips: string[];
  onSave: (reading: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const submit = () => {
    const reading = value.trim();
    if (reading && !isKana(reading)) {
      setError("읽기는 가나로만 입력해 주세요");
      return;
    }
    setSaving(true);
    onSave(reading).catch(() => {
      setError("이름을 저장하지 못했습니다. 다시 시도해 주세요.");
      setSaving(false);
    });
  };
  return (
    <form
      className="name-editor"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label>
        읽기
        <input
          lang="ja"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setError(undefined);
          }}
        />
      </label>
      {chips.length > 0 && (
        <div className="name-chips">
          {chips.map((chip) => (
            <button
              key={chip}
              type="button"
              lang="ja"
              onClick={() => {
                setValue(chip);
                setError(undefined);
              }}
            >
              {chip}
            </button>
          ))}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <div className="name-actions">
        <button type="submit" className="primary-button" disabled={saving}>
          저장
        </button>
        <button type="button" className="text-button" onClick={onCancel}>
          취소
        </button>
      </div>
    </form>
  );
}

// 이름 행: 표기, 읽기(있으면), '내가 지정한 이름'. 뜻·태그·사전 각주·배지는 없다.
function NameRow({
  surface,
  reading,
  dragged,
  onShowWord,
  onEdit,
  onRemove,
}: {
  surface: string;
  reading: string | null;
  dragged: boolean;
  onShowWord: () => void;
  onEdit: () => void;
  onRemove: () => Promise<void>;
}) {
  const [error, setError] = useState<string>();
  return (
    <>
      <BadgeRow dragged={dragged} />
      <div className="word-head">
        <h3 lang="ja">{surface}</h3>
        {reading && (
          <span lang="ja" className="word-reading">
            {reading}
          </span>
        )}
      </div>
      <p className="name-mark">내가 지정한 이름</p>
      <div className="name-actions">
        <button type="button" aria-pressed={false} onClick={onShowWord}>
          사전 단어 보기
        </button>
        <button type="button" onClick={onEdit}>
          읽기 고치기
        </button>
        <button
          type="button"
          className="text-button name-remove"
          onClick={() =>
            onRemove().catch(() =>
              setError("지정을 해제하지 못했습니다. 다시 시도해 주세요."),
            )
          }
        >
          지정 해제
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </>
  );
}

// 단어 행: 배지 줄, 사전형(표제)·읽기, 태그, 이 문장에서 고른 뜻. 드래그 범위와 겹친 단어를 먼저 두고,
// 각 묶음 안은 원문 순서로 보인다. 뜻을 아직 고르지 않았거나 한국어 뜻이 아직 없는 단어는 뜻 자리에 대기 표시를 둔다.
// 사전(JMdict) 단어가 있으면 목록 아래에 출처 각주를 단다. LLM이 만든 단어만 있으면 달지 않는다(#134).
// 지정한 이름과 표층형이 같은 단어는 이름 행으로 보인다(#136). '사전 단어 보기'(asWord)로 그 자리만
// 단어 행으로 바꿔 볼 수 있다.
export function WordList({
  text,
  words,
  ruby,
  selection,
  names,
  asWord,
  onToggleAsWord,
  onSave,
  onRemove,
}: {
  text: string;
  words: WordItem[];
  ruby: RubyItem[];
  selection: DragRange;
  names: ReadonlyMap<string, string | null>;
  asWord: ReadonlySet<string>;
  onToggleAsWord: (key: string) => void;
} & NameActions) {
  // 읽기 입력을 연 단어 자리
  const [editing, setEditing] = useState<string>();
  if (words.length === 0) {
    return <p className="no-words">단어 없음</p>;
  }
  const sorted = [...words].sort((a, b) => a.start - b.start || a.end - b.end);
  const named = new Set(
    namedWords(text, words, names, asWord).map(({ word }) => wordKey(word)),
  );
  const fromDictionary = words.some(
    (word) => word.in_dictionary && !named.has(wordKey(word)),
  );
  return (
    <>
      <ul className="word-list" aria-label="단어">
        {draggedFirst(sorted, selection).map(({ item: word, dragged }) => {
          const key = wordKey(word);
          const surface = text.slice(word.start, word.end);
          const designated = names.has(surface);
          const editor = editing === key && (
            <NameEditor
              initial={
                (designated && names.get(surface)) ||
                sudachiReading(text, word, ruby)
              }
              chips={
                word.in_dictionary && isKana(word.reading) ? [word.reading] : []
              }
              onSave={(reading) =>
                onSave(surface, reading).then(() => setEditing(undefined))
              }
              onCancel={() => setEditing(undefined)}
            />
          );
          if (named.has(key)) {
            return (
              <li
                key={key}
                className={dragged ? "word-row dragged" : "word-row"}
              >
                <NameRow
                  surface={surface}
                  reading={names.get(surface)!}
                  dragged={dragged}
                  onShowWord={() => onToggleAsWord(key)}
                  onEdit={() => setEditing(key)}
                  onRemove={() => onRemove(surface)}
                />
                {editor}
              </li>
            );
          }
          const tags = tagNames(word);
          return (
            <li key={key} className={dragged ? "word-row dragged" : "word-row"}>
              <BadgeRow {...senseBadges(word.sense)} dragged={dragged} />
              <div className="word-head">
                <h3 lang="ja">{word.dictionary_form}</h3>
                <span lang="ja" className="word-reading">
                  {word.reading}
                </span>
              </div>
              {tags.length > 0 && (
                <ul className="word-tags" aria-label="태그">
                  {tags.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              )}
              {word.sense ? <Meaning sense={word.sense} /> : <Preparing />}
              <div className="name-actions">
                {designated ? (
                  <button
                    type="button"
                    aria-pressed={true}
                    onClick={() => onToggleAsWord(key)}
                  >
                    사전 단어 보기
                  </button>
                ) : (
                  editing !== key && (
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => setEditing(key)}
                    >
                      이름으로 지정
                    </button>
                  )
                )}
              </div>
              {editor}
            </li>
          );
        })}
      </ul>
      {fromDictionary && (
        <p className="source-note">
          단어 정보:{" "}
          <a
            href="https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project"
            target="_blank"
            rel="noreferrer"
          >
            JMdict
          </a>{" "}
          (EDRDG,{" "}
          <a
            href="https://creativecommons.org/licenses/by-sa/4.0/"
            target="_blank"
            rel="noreferrer"
          >
            CC BY-SA 4.0
          </a>
          ). 이 문장에 맞는 뜻만 골라 보여 줘요.
        </p>
      )}
    </>
  );
}
