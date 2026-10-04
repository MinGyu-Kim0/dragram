import { useEffect, useState } from "react";

import { api } from "../../api";

type Vocabulary = {
  surface: string;
  dictionary_form: string;
  reading_form: string;
  part_of_speech: string[];
};

type Grammar = {
  name_ja: string;
  name_ko: string;
  summary: string;
  evidence: string;
};

type SavedSentence = {
  sentence_id: number;
  normalized_text: string;
  meaning_ko: string;
  explanation: string;
  model: string;
  source_url: string;
  source_title: string;
  vocabulary: Vocabulary[];
  grammars: Grammar[];
};

export default function SentenceLibrary() {
  const [sentences, setSentences] = useState<SavedSentence[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ sentences: SavedSentence[] }>("/sentences/")
      .then(({ sentences: saved }) => setSentences(saved))
      .catch((reason: Error) => setError(reason.message));
  }, []);

  return (
    <section id="review" className="review">
      <div className="section-heading">
        <span className="eyebrow">Dashboard</span>
        <h2>저장한 문장 복습</h2>
      </div>
      {error && <p className="error">{error}</p>}
      {!error && sentences === null && <p className="empty">저장한 문장을 불러오는 중입니다.</p>}
      {!error && sentences?.length === 0 && (
        <p className="empty">아직 저장된 문장이 없습니다. 웹에서 일본어 문장을 드래그해 보세요.</p>
      )}
      <div className="review-grid">
        {sentences?.map((sentence) => (
          <article className="review-card" key={sentence.sentence_id}>
            <div className="sentence-heading">
              <div>
                <span className="model">{sentence.model.replace("gpt-5.6-", "")}</span>
                <h3>{sentence.normalized_text}</h3>
              </div>
              {sentence.source_url && (
                <a href={sentence.source_url} target="_blank" rel="noreferrer">
                  {sentence.source_title || "출처 보기"}
                </a>
              )}
            </div>
            <p className="meaning">{sentence.meaning_ko}</p>
            <p className="explanation">{sentence.explanation}</p>

            <h4>어휘</h4>
            <div className="vocabulary">
              {sentence.vocabulary.map((word, index) => (
                <span className="word" key={`${word.surface}-${index}`} title={word.part_of_speech.join(" · ")}>
                  <strong>{word.dictionary_form || word.surface}</strong>
                  <small>{word.reading_form || word.surface}</small>
                </span>
              ))}
            </div>

            <h4>문법</h4>
            {sentence.grammars.length === 0 ? (
              <p className="empty compact">별도의 문법 패턴이 없습니다.</p>
            ) : (
              <div className="grammar-list">
                {sentence.grammars.map((grammar) => (
                  <div className="grammar" key={grammar.name_ja}>
                    <strong>{grammar.name_ja} · {grammar.name_ko}</strong>
                    <span>{grammar.summary}</span>
                    <small>{grammar.evidence}</small>
                  </div>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
