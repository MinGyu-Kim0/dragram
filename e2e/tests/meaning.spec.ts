import { expect, test } from "@playwright/test";
import { meaningInTranslation } from "../support/meaning";

// 시나리오 5의 판정 규칙(#438). 브라우저 없이 돈다.
test("단어 뜻이 번역에 들어 있는지 어간 일치로 너그럽게 본다", () => {
  const cases: [string, string, boolean][] = [
    // 명사는 그대로 찾는다.
    ["비", "비가 와서 집에 있었다.", true],
    ["신문", "매일 아침 역 근처 가게에서 신문을 삽니다.", true],
    // 쉼표로 이은 비슷한 말 가운데 하나만 있으면 된다. 괄호 풀이는 뗀다.
    ["가게, 상점", "근처 상점에서", true],
    ["(물건을) 사다", "신문을 삽니다.", true],
    // 활용: 한 음절 어간은 받침까지, 여러 음절 어간은 마지막 자모를 빼고 비교한다.
    ["사다", "어제 샀다.", true],
    ["마시다", "차가운 물을 마셨습니다.", true],
    ["차갑다", "차가운 물", true],
    ["쓰다, 적다", "큰 글씨를 적었습니다.", true],
    ["식사하다", "같이 식사했다.", true],
    // 한 음절 어간의 'ㅡ'는 활용하면 빠진다(쓰다 → 썼다). 받침 ㅆ(있었다)과는 다르다.
    ["쓰다, 작문하다", "큰 글씨를 썼습니다.", true],
    ["쓰다", "칠판에 있었습니다.", false],
    // 없으면 거짓이다.
    ["칠판", "선생님은 큰 글씨를 썼습니다.", false],
    ["사다", "신문을 읽습니다.", false],
  ];
  for (const [meaning, translation, expected] of cases)
    expect(meaningInTranslation(meaning, translation), meaning).toBe(expected);
});
