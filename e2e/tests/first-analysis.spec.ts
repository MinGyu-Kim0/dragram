import {
  analyzeSelection,
  expect,
  expectAnalysisDone,
  openArticle,
  openPanel,
  recordPanel,
  signInAndConnect,
  test,
} from "../support/fixtures";
import { FIRST_ANALYSIS } from "../fixtures/sentences";

// 시나리오 1: 새 문장 첫 분석(요구사항 2절 기본 사용 시나리오, #397).
// 실제 모델의 답은 매번 달라 번역문·용법 이름은 비교하지 않고, 흔들리지 않는 사실만 본다.
test("새 문장 첫 분석: DB 결과가 먼저 보이고 번역·판별 결과가 이어서 채워진다", async ({
  context,
}) => {
  const { sentence, drag, confirmed, checking, word } = FIRST_ANALYSIS;
  await signInAndConnect(context, `first-${Date.now()}@e2e.test`);
  const panel = await openPanel(context);
  const article = await openArticle(context, sentence);

  const states = await recordPanel(panel);
  await analyzeSelection(context, article, drag);

  const grammar = panel.getByRole("list", { name: "문법" });
  const card = (pattern: string) =>
    grammar.getByRole("listitem").filter({ hasText: pattern }).first();
  const loadingTranslation = panel.getByRole("status", {
    name: "번역을 불러오는 중",
  });

  // 드래그한 일부가 문장 하나로 넓혀져 패널에 보인다(앞뒤 문장은 들어가지 않는다).
  // 원문에는 한자 루비가 붙으므로 루비 없는 끝부분과 다음 문장의 글자로 확인한다.
  const original = panel.getByRole("region", { name: "원문" });
  await expect(original).toContainText("ます。");
  await expect(original).not.toContainText("以上");

  // 번역이 원문 카드에 채워진다.
  await expect(loadingTranslation).toBeHidden();
  // 그 전에 DB로 확정한 문법(승인된 용법 하나뿐인 패턴, 미검수 배지 없음), 판별 대상 구간의
  // '확인 중' 카드, 같은 이벤트로 온 사전 단어가 보였다.
  const early = (await states()).filter((state) => state.loadingTranslation);
  expect(
    early.some((state) =>
      state.grammarCards.some(
        (c) => c.includes(confirmed) && !c.includes("AI 생성·미검수"),
      ),
    ),
    "DB 확정 카드가 번역보다 먼저",
  ).toBe(true);
  expect(
    early.some((state) =>
      state.grammarCards.some(
        (c) => c.includes(checking) && c.includes("확인 중"),
      ),
    ),
    "확인 중 카드가 번역보다 먼저",
  ).toBe(true);
  expect(
    early.some((state) => /^단어 [1-9]/.test(state.wordsTab ?? "")),
    "사전 단어가 번역보다 먼저",
  ).toBe(true);
  await expect(
    original.getByRole("paragraph").filter({ hasText: /[가-힣]/ }),
  ).toBeVisible();

  // 판별 결과가 오면 '확인 중'이 모두 사라진다.
  await expect(panel.getByRole("status", { name: "분석 중" })).toBeHidden();
  await expect(grammar.getByText("확인 중", { exact: true })).toHaveCount(0);
  // LLM이 만든 지식(미검수 패턴의 용법)은 '미검수'로, 승인된 지식은 배지 없이 보인다.
  await expect(card(checking)).toContainText("AI 생성·미검수");
  await expect(card(confirmed)).not.toContainText("AI 생성·미검수");

  // 시드한 사전 단어가 단어 탭에 보이고, 사전을 옮긴 검수 안 된 뜻은 'AI 번역'으로 보인다.
  await panel.getByRole("tab", { name: /^단어/ }).click();
  const row = panel
    .getByRole("list", { name: "단어" })
    .getByRole("listitem")
    .filter({ has: panel.getByRole("heading", { name: word, exact: true }) });
  await expect(row).toContainText("AI 번역");
  await expectAnalysisDone(panel);
});
