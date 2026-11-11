import { analysisLlmCalls, requestPaths } from "../support/db";
import {
  analyzeSelection,
  expect,
  expectAnalysisDone,
  launchBrowser,
  openArticle,
  openPanel,
  recordPanel,
  signInAndConnect,
  test,
} from "../support/fixtures";
import { CACHE_REUSE } from "../fixtures/sentences";

// 시나리오 2: 캐시 재사용(요구사항 2절 기본 사용 시나리오 4, #435).
test("다른 사용자가 같은 문장을 분석하면 LLM 호출 없이 저장된 결과가 바로 보인다", async ({
  context,
}) => {
  const { sentence, drag } = CACHE_REUSE;

  // 첫 사용자가 분석해 공용 캐시에 넣는다.
  const firstEmail = `cache-first-${Date.now()}@e2e.test`;
  await signInAndConnect(context, firstEmail);
  const firstPanel = await openPanel(context);
  await analyzeSelection(context, await openArticle(context, sentence), drag);
  await expectAnalysisDone(firstPanel);
  // 정말 새 문장이었다(이미 캐시에 있었으면 아래 확인이 아무것도 보장하지 않는다).
  expect(await requestPaths(firstEmail)).toEqual(["llm"]);
  const before = await analysisLlmCalls();

  // 다른 사용자(새 브라우저, 새 계정)가 같은 문장을 분석한다.
  const other = await launchBrowser();
  try {
    const email = `cache-second-${Date.now()}@e2e.test`;
    await signInAndConnect(other, email);
    const panel = await openPanel(other);
    const states = await recordPanel(panel);
    await analyzeSelection(other, await openArticle(other, sentence), drag);
    await expectAnalysisDone(panel);

    // 번역(expectAnalysisDone)과 문법이 보인다.
    await expect(
      panel.getByRole("list", { name: "문법" }).getByRole("listitem").first(),
    ).toBeVisible();
    // 저장된 결과가 한 번에 왔다: 판별을 기다리는 '확인 중'이나 '분석 중'이 한 번도 보이지 않았다.
    const seen = await states();
    expect(
      seen.some((state) => state.analyzing),
      "분석 중이 보임",
    ).toBe(false);
    expect(
      seen.some((state) =>
        state.grammarCards.some((c) => c.includes("확인 중")),
      ),
      "확인 중이 보임",
    ).toBe(false);

    // 운영자 쪽: 문장 분석 LLM 호출이 늘지 않았고, 요청은 LLM 없는 경로로 기록됐다. 첫 분석이 새
    // 패턴을 등록해 패턴 세트 버전이 올랐으면 저장 결과를 LLM 없이 다시 매칭한다(db), 아니면 그대로
    // 보낸다(cache).
    expect(await analysisLlmCalls()).toBe(before);
    const paths = await requestPaths(email);
    expect(paths).toHaveLength(1);
    expect(["cache", "db"]).toContain(paths[0]);
  } finally {
    await other.close();
  }
});
