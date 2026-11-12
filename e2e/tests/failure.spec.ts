import { analysisStatuses } from "../support/db";
import {
  analyzeSelection,
  expect,
  openArticle,
  openPanel,
  signInAndConnect,
  test,
} from "../support/fixtures";
import { LLM_FAILURE, USAGE_LIMIT } from "../fixtures/sentences";

// 시나리오 4: 실패·한도(#437). 설정만 바꾼 스택에서 돈다. 태그가 스택 이름이다(stacks/, run.sh).

test(
  "LLM 호출이 실패하면 오류와 다시 시도가 보이고, 실패한 분석은 캐시에 저장되지 않는다",
  { tag: "@llm-failure" },
  async ({ context }) => {
    const { sentence, drag } = LLM_FAILURE;
    const email = `llm-failure-${Date.now()}@e2e.test`;
    await signInAndConnect(context, email);
    const panel = await openPanel(context);
    await analyzeSelection(context, await openArticle(context, sentence), drag);

    await expect(panel.getByText(/분석하지 못했습니다/)).toBeVisible();
    await expect(panel.getByRole("button", { name: "다시 시도" })).toBeVisible();
    // 운영자 쪽: 요청이 맡은 공용 분석 행이 실패로 남았다(완료 행만 캐시로 내준다).
    await expect.poll(() => analysisStatuses(email)).toEqual(["failed"]);
  },
);

test(
  "하루 토큰 한도를 넘기면 한도 안내가 보인다",
  { tag: "@usage-limit" },
  async ({ context }) => {
    const { sentence, drag } = USAGE_LIMIT;
    await signInAndConnect(context, `usage-limit-${Date.now()}@e2e.test`);
    const panel = await openPanel(context);
    await analyzeSelection(context, await openArticle(context, sentence), drag);

    await expect(
      panel.getByText(
        "오늘 쓸 수 있는 분석량을 다 썼습니다. 내일 다시 시도해 주세요.",
      ),
    ).toBeVisible();
    await expect(panel.getByRole("button", { name: "다시 시도" })).toBeVisible();
  },
);
