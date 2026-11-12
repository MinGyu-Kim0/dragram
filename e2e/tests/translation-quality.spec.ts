import {
  analyzeSelection,
  expect,
  expectAnalysisDone,
  openArticle,
  openPanel,
  signInAndConnect,
  test,
} from "../support/fixtures";
import { meaningInTranslation } from "../support/meaning";
import { TRANSLATION_QUALITY } from "../fixtures/sentences";

// 번역에 단어 카드 뜻이 들어 있어야 하는 최소 비율(세 문장 합, 카드 16장). 2026-11-12 실제 실행
// 5회가 1.00 네 번·0.94 한 번(기차역 → 역)이었다. 모델이 말을 바꿔 쓰는 정도(넉 장까지)는 넘기고,
// 여러 단어를 빠뜨린 번역은 잡는다.
const MIN_RATIO = 0.75;

// 시나리오 5: 번역 품질(#438, #397 사용자 이야기 22·23). 번역문을 비교하지 않고, 그 문장 단어
// 카드의 한국어 뜻이 번역에 얼마나 들어 있는지 비율로 본다.
test("고정 문장의 번역이 단어 카드의 한국어 뜻을 기준 비율 이상 담는다", async ({
  context,
}) => {
  await signInAndConnect(context, `quality-${Date.now()}@e2e.test`);
  let found = 0;
  let total = 0;
  for (const sentence of TRANSLATION_QUALITY) {
    const panel = await openPanel(context);
    const article = await openArticle(context, sentence);
    await analyzeSelection(context, article, sentence);
    await expectAnalysisDone(panel);
    const translation = await panel
      .getByRole("region", { name: "원문" })
      .getByRole("paragraph")
      .filter({ hasText: /[가-힣]/ })
      .innerText();

    await panel.getByRole("tab", { name: /^단어/ }).click();
    const words = panel.getByRole("list", { name: "단어" });
    await expect(
      words.getByRole("status", { name: "뜻을 준비하는 중" }),
    ).toHaveCount(0);
    // 뜻 줄('뜻' 라벨 + 한국어 뜻). 뜻을 만들지 못한 카드는 비교할 뜻이 없어 세지 않는다.
    const meanings = (
      await words
        .getByRole("paragraph")
        .filter({ has: panel.getByText("뜻", { exact: true }) })
        .allInnerTexts()
    ).map((line) => line.replace(/^뜻\s*/, ""));
    expect(meanings.length, `${sentence}의 단어 뜻`).toBeGreaterThan(0);

    const hits = meanings.filter((m) => meaningInTranslation(m, translation));
    const missed = meanings.filter((m) => !hits.includes(m));
    console.log(
      `${sentence} → ${translation}\n  ${hits.length}/${meanings.length}` +
        (missed.length ? ` (없음: ${missed.join(" / ")})` : ""),
    );
    found += hits.length;
    total += meanings.length;
    await article.close();
    await panel.close();
  }
  const ratio = found / total;
  console.log(
    `합계 ${found}/${total} = ${ratio.toFixed(2)} (기준 ${MIN_RATIO})`,
  );
  expect(ratio, "단어 뜻 포함 비율").toBeGreaterThanOrEqual(MIN_RATIO);
});
