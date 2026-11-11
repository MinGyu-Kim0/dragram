import { test as base, chromium, expect } from "@playwright/test";
import type { BrowserContext, Page, Worker } from "@playwright/test";

// wxt.config.ts의 개발용 공개 키로 고정한 확장 ID(웹 VITE_EXTENSION_ID 기본값과 같다).
export const EXTENSION_ID = "ilhnmbeleinmgfcigakmfobgngiillah";
export const WEB = "http://localhost:5173";
// 테스트용 일본어 페이지는 Playwright가 이 주소로 내준다. 확장 host_permissions(API 출처) 안이라
// 우클릭 메뉴와 같은 문장 추출 스크립트가 주입된다(사람이 누를 때는 activeTab으로 주입된다).
const ARTICLE = "http://localhost:8000/e2e/article.html";

// 서비스 워커 안에서 도는 코드(worker.evaluate)가 쓰는 확장 API. 메뉴 이벤트의 dispatch는 타입에 없다.
declare const chrome: any;

// 시나리오마다 새 브라우저(새 확장 저장소)로 시작한다.
export const test = base.extend<{ context: BrowserContext }>({
  context: async ({}, use) => {
    const extension = process.env.EXTENSION_PATH;
    if (!extension)
      throw new Error("EXTENSION_PATH가 없다(e2e/run.sh로 실행한다)");
    const context = await chromium.launchPersistentContext("", {
      channel: "chromium",
      locale: "ko-KR",
      args: [
        `--disable-extensions-except=${extension}`,
        `--load-extension=${extension}`,
      ],
    });
    await use(context);
    await context.close();
  },
});
export { expect };

async function serviceWorker(context: BrowserContext): Promise<Worker> {
  return (
    context.serviceWorkers()[0] ?? (await context.waitForEvent("serviceworker"))
  );
}

// dev-login으로 웹 세션을 만들고, 웹 '로그인·확장 연결' 화면에서 실제로 연결한다.
export async function signInAndConnect(context: BrowserContext, email: string) {
  const page = await context.newPage();
  await page.goto(`${WEB}/connect`);
  // 화면이 처음 부르는 /api/auth/me가 CSRF 쿠키를 준다.
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const status = await page.evaluate(async (email) => {
    const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? "";
    const response = await fetch("/api/auth/dev-login/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ email }),
    });
    return response.status;
  }, email);
  expect(status, "dev-login").toBe(200);
  await page.reload();
  await page.getByRole("button", { name: "확장 프로그램 연결" }).click();
  await expect(page.getByRole("heading", { name: "연결했어요" })).toBeVisible();
  await page.close();
}

// 사이드 패널은 사용자 동작 안에서만 열리므로 같은 화면을 같은 창의 탭으로 연다.
// 패널은 자기 창의 분석 요청을 받으므로, 페이지 탭과 같은 창이면 똑같이 동작한다.
export async function openPanel(context: BrowserContext): Promise<Page> {
  const panel = await context.newPage();
  await panel.goto(`chrome-extension://${EXTENSION_ID}/sidepanel.html`);
  return panel;
}

// 고정 문장을 담은 일본어 페이지를 연다. 앞뒤 문장은 드래그를 문장으로 넓히는지 보려고 둔다.
export async function openArticle(
  context: BrowserContext,
  sentence: string,
): Promise<Page> {
  await context.route(ARTICLE, (route) =>
    route.fulfill({
      contentType: "text/html; charset=utf-8",
      body: `<!doctype html><html lang="ja"><body><p id="text">今日の話です。${sentence}以上です。</p></body></html>`,
    }),
  );
  const page = await context.newPage();
  await page.goto(ARTICLE);
  return page;
}

// 문장 일부를 드래그하고 우클릭 메뉴 "Dragram으로 분석"을 누른 것과 같은 처리를 부른다.
// Playwright는 크롬 우클릭 메뉴를 누를 수 없어, 백그라운드의 메뉴 클릭 이벤트를 직접 보낸다.
export async function analyzeSelection(
  context: BrowserContext,
  page: Page,
  part: string,
) {
  const selected = await page.evaluate((part) => {
    const node = document.getElementById("text")!.firstChild as Text;
    const start = node.data.indexOf(part);
    if (start < 0) return "";
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, start + part.length);
    getSelection()!.removeAllRanges();
    getSelection()!.addRange(range);
    return getSelection()!.toString();
  }, part);
  expect(selected, "드래그한 글자").toBe(part);
  const worker = await serviceWorker(context);
  await worker.evaluate(
    async ({ url, part }) => {
      const [tab] = await chrome.tabs.query({ url });
      chrome.contextMenus.onClicked.dispatch(
        { menuItemId: "analyze-selection", selectionText: part, frameId: 0 },
        tab,
      );
    },
    { url: ARTICLE, part },
  );
}
