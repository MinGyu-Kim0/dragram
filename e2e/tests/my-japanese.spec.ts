import { columnsContaining } from "../support/db";
import {
  analyzeSelection,
  expect,
  expectAnalysisDone,
  launchBrowser,
  openArticle,
  openPanel,
  signIn,
  signInAndConnect,
  test,
  WEB,
} from "../support/fixtures";
import { MY_JAPANESE } from "../fixtures/sentences";

// 시나리오 3: 내 일본어 조회·원문 보호(#436, #397 사용자 이야기 16~18).
test("사이드 패널에서 추가한 항목은 본인 '내 일본어'에만 보이고, 원문은 본인 예문에만 남는다", async ({
  context,
}) => {
  const { sentence, drag, grammar, word } = MY_JAPANESE;

  // 사이드 패널에서 문법 카드를 추가하고 이 문장을 예문으로 저장하고, 단어를 추가한다.
  await signInAndConnect(context, `mine-${Date.now()}@e2e.test`);
  const panel = await openPanel(context);
  await analyzeSelection(context, await openArticle(context, sentence), drag);
  await expectAnalysisDone(panel);

  // 칩 글자가 정확히 그 패턴인 카드. 구성 문법이면 바깥 카드와 하위 박스가 함께 걸리므로 가장
  // 안쪽(마지막) 것을 고르고, 버튼도 하위 박스 버튼 뒤에 오는 그 카드 자신의 것(마지막)을 누른다.
  const grammarCard = panel
    .getByRole("list", { name: "문법" })
    .getByRole("listitem")
    .filter({ has: panel.getByText(grammar, { exact: true }) })
    .last();
  await grammarCard
    .getByRole("button", { name: "추가", exact: true })
    .last()
    .click();
  await grammarCard.getByRole("button", { name: "예문 저장" }).last().click();
  await expect(grammarCard.getByText("예문 저장됨")).toBeVisible();

  await panel.getByRole("tab", { name: /^단어/ }).click();
  const wordRow = panel
    .getByRole("list", { name: "단어" })
    .getByRole("listitem")
    .filter({ has: panel.getByRole("heading", { name: word, exact: true }) });
  await wordRow.getByRole("button", { name: "추가", exact: true }).click();
  await expect(wordRow.getByRole("button", { name: "추가됨" })).toBeVisible();

  // 웹 '내 기록'에 추가한 문법(고른 예문 포함)과 단어가 보인다.
  const records = await context.newPage();
  await records.goto(`${WEB}/sentences`);
  const addedGrammar = records.getByRole("list", { name: "추가한 문법" });
  await expect(addedGrammar.getByRole("listitem").first()).toContainText(
    grammar,
  );
  await expect(
    addedGrammar.getByRole("list", { name: "내 예문" }),
  ).toContainText(sentence);
  await records.getByRole("tab", { name: "단어" }).click();
  await expect(
    records.getByRole("list", { name: "추가한 단어" }).getByRole("heading", {
      name: word,
      exact: true,
    }),
  ).toBeVisible();

  // 다른 계정의 '내 기록'에는 보이지 않는다.
  const other = await launchBrowser();
  try {
    const page = await signIn(other, `mine-other-${Date.now()}@e2e.test`);
    await page.goto(`${WEB}/sentences`);
    await expect(
      page.getByText("추가한 문법이 아직 없어요.", { exact: false }),
    ).toBeVisible();
    await expect(page.locator("body")).not.toContainText(sentence);
    await page.getByRole("tab", { name: "단어" }).click();
    await expect(
      page.getByText("추가한 단어가 아직 없어요.", { exact: false }),
    ).toBeVisible();
  } finally {
    await other.close();
  }

  // 운영자 쪽: 원문은 본인이 고른 예문(my_example)에만 있고 공용 테이블 어디에도 없다.
  // 끝 마침표를 뗀 글자로 찾아, 마침표를 다듬어 저장한 칸도 놓치지 않는다.
  expect(await columnsContaining(sentence.replace(/。$/, ""))).toEqual([
    "my_example.original_text",
  ]);
});
