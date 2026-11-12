// 시나리오 5(#438)의 판정: 단어 카드의 한국어 뜻이 번역문에 들어 있는가.
// 모델 번역은 매번 달라 정확히 비교하지 않고, 어미 활용을 어간 일치 정도로 너그럽게 본다.

// 한글을 자모로 푼다. 활용하면 음절이 합쳐지므로(사 + ㅂ니다 → 삽니다) 자모로 비교한다.
const jamo = (text: string) => text.normalize("NFD");

// 뜻 말 하나("사다")를 번역에서 찾을 꼴로. '다'로 끝나는 말(동사·형용사)은 어간만 남기고, 어간이
// 여러 음절이면 마지막 자모를 뗀다(마시 → 마ㅅ: 마셨다, 차갑 → 차가: 차가운). 한 음절 어간은
// 그대로 둔다(사: 삽니다·샀다). 하나만 남기면 아무 글자에나 맞기 때문이다. 다만 'ㅡ'로 끝나는
// 한 음절 어간은 활용하면 'ㅡ'가 빠지므로 첫소리만 본다(쓰 → ㅆ: 썼다). 받침 ㅆ(있었다)은 자모가 달라
// 맞지 않는다.
function needle(word: string) {
  if (word.length < 2 || !word.endsWith("다")) return jamo(word);
  const stem = jamo(word.slice(0, -1));
  if (word.length > 2) return stem.slice(0, -1);
  return stem.endsWith("ᅳ") ? stem.slice(0, -1) : stem;
}

// 쉼표로 이은 비슷한 말("가게, 상점") 가운데 하나라도 번역에 있으면 참이다. 괄호 풀이는 뗀다.
export function meaningInTranslation(meaning: string, translation: string) {
  const text = jamo(translation);
  return meaning
    .replace(/\([^)]*\)/g, "")
    .split(/[,;]/)
    .map((word) => word.trim())
    .filter(Boolean)
    .some((word) => text.includes(needle(word)));
}
