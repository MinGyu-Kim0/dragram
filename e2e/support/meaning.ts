// 시나리오 5(#438)의 판정: 단어 카드의 한국어 뜻이 번역문에 들어 있는가.
// 모델 번역은 매번 달라 정확히 비교하지 않고, 어미 활용을 어간 일치 정도로만 너그럽게 본다.
// 활용하면 음절이 합쳐지므로(사 + ㅂ니다 → 삽니다) 한글을 자모(NFD)로 풀어 비교한다.

const jamo = (text: string) => text.normalize("NFC").normalize("NFD");
// 자모 앞에 자모가 없어야 어절 맨 앞이다(남동생의 '동생', 글씨의 'ㅆ'에 맞지 않게).
const WORD_START = "(?<![\\u1100-\\u11FF])";
// 받침(종성) 자모 범위와, 열린 한 음절 어간 뒤에 활용으로 붙는 받침(산·살·삼·삽·샀)
const FINAL = "[\\u11A8-\\u11C2]";
const ENDING_FINAL = "[\\u11AB\\u11AF\\u11B7\\u11B8\\u11BB]";
const EU = "ᅳ"; // ㅡ
const EO_A = "[\\u1161\\u1165]"; // ㅏ·ㅓ

// 뜻 낱말 하나("사다")를 번역에서 찾을 정규식으로. 모두 어절 맨 앞에서만 맞는다.
// - '다'로 끝나지 않는 말(명사 등)은 그대로 찾는다.
// - 여러 음절 어간은 마지막 자모를 빼고 찾는다(마시 → 마ㅅ: 마셨다, 차갑 → 차가: 차가운).
// - 한 음절 어간은 그 음절을 찾되, 받침 없는 어간이면 뒤에 활용 받침만 붙을 수 있다(사: 삽니다·샀다,
//   상점은 아니다). 'ㅡ'로 끝나면 활용하며 'ㅡ'가 빠지므로 첫소리 + ㅏ·ㅓ도 맞는다(쓰 → 썼다).
function wordPattern(word: string) {
  const syllables = [...word.normalize("NFC")];
  if (syllables.length < 2 || syllables.at(-1) !== "다")
    return WORD_START + escape(jamo(word));
  const stem = jamo(syllables.slice(0, -1).join(""));
  if (syllables.length > 2) return WORD_START + escape(stem.slice(0, -1));
  if (new RegExp(`${FINAL}$`).test(stem)) return WORD_START + escape(stem);
  const open = `${escape(stem)}(?:${ENDING_FINAL}|(?!${FINAL}))`;
  return stem.endsWith(EU)
    ? `${WORD_START}(?:${open}|${escape(stem[0]!)}${EO_A})`
    : WORD_START + open;
}

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// 뜻 하나를 찾을 낱말들로. ~로 시작하는 말은 붙는 조사 안내라(~에 쓰다) 다른 낱말이 있으면 빼고,
// 그것뿐이면 ~만 뗀다(~하다).
function phraseWords(phrase: string) {
  const words = phrase.trim().split(/\s+/).filter(Boolean);
  const content = words.filter((word) => !word.startsWith("~"));
  return (content.length ? content : words).map((word) =>
    word.replace(/^~/, ""),
  );
}

// 쉼표로 이은 비슷한 말("가게, 상점") 가운데 하나라도 번역에 있으면 참이다. 괄호 풀이는 떼고, 띄어
// 쓴 뜻("매일 아침")은 낱말마다 찾는다.
export function meaningInTranslation(meaning: string, translation: string) {
  const text = jamo(translation);
  return meaning
    .replace(/\([^)]*\)/g, "")
    .split(/[,;]/)
    .map(phraseWords)
    .filter((words) => words.length > 0 && words.every(Boolean))
    .some((words) =>
      words.every((word) => new RegExp(wordPattern(word), "u").test(text)),
    );
}
