// 스토어 스크린샷 4장과 홍보 이미지 3장을 1280×800으로 만든다(#398).
// 사용: node shots.mjs <빌드 폴더> <출력 폴더>. run.sh가 Playwright 컨테이너 안에서 부른다.
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";

const [, , site, out] = process.argv;
const here = path.dirname(new URL(import.meta.url).pathname);
const work = fs.mkdtempSync(path.join(os.tmpdir(), "store-shots-"));
fs.mkdirSync(path.join(out, "promo"), { recursive: true });

// 빌드 결과를 그대로 내준다. 가이드 화면은 예시 데이터가 고정돼 있어 서버가 필요 없다.
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};
const server = http
  .createServer((req, res) => {
    const file = path.join(
      site,
      decodeURIComponent(new URL(req.url, "http://x").pathname),
    );
    fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(404).end();
        return;
      }
      res.setHeader(
        "Content-Type",
        types[path.extname(file)] ?? "application/octet-stream",
      );
      res.end(data);
    });
  })
  .listen(0);
const base = `http://localhost:${server.address().port}`;

// 설명 덮개를 숨겨 장면만 남기고, Windows Chrome처럼 한글은 맑은 고딕, 일본어는 Yu Gothic으로 보인다.
const style = `.guide-spot,.guide-arrow,.guide-box{display:none!important}
body{font-family:"Segoe UI","Malgun Gothic","Yu Gothic UI",sans-serif!important}`;

const browser = await chromium.launch();
async function guide(options) {
  const page = await browser.newPage({ colorScheme: "light", ...options });
  await page.goto(`${base}/guide.html`);
  await page.waitForSelector(".guide-box");
  await page.addStyleTag({ content: style });
  await page.evaluate(() => document.fonts.ready);
  return page;
}

// 1) 스크린샷: 가이드 장면을 1280×800 그대로.
const shots = {
  0: "1-분석-시작",
  3: "2-선택한-카드",
  9: "3-문법-카드",
  10: "4-단어-카드",
};
const page = await guide({ viewport: { width: 1280, height: 800 } });
for (let i = 0; i <= 10; i++) {
  await page.waitForTimeout(400);
  if (shots[i]) await page.screenshot({ path: `${out}/${shots[i]}.png` });
  await page.keyboard.press("ArrowRight");
}

// 2) 홍보 이미지 재료: 우클릭 장면 전체와 패널만 잘라 2배율로.
const panels = { 3: "panel-selected", 7: "panel-grammar", 10: "panel-words" };
const crop = await guide({
  viewport: { width: 1280, height: 800 },
  deviceScaleFactor: 2,
});
for (let i = 0; i <= 10; i++) {
  await crop.waitForTimeout(400);
  if (i === 0) {
    await crop.screenshot({ path: `${work}/scene-menu.png` });
    await crop.setViewportSize({ width: 1280, height: 1000 });
  }
  if (panels[i]) {
    await crop.evaluate(() =>
      document
        .querySelectorAll(".fake-panel, .fake-panel *")
        .forEach((el) => (el.scrollTop = 0)),
    );
    await crop.waitForTimeout(200);
    await crop
      .locator(".fake-panel")
      .screenshot({ path: `${work}/${panels[i]}.png` });
  }
  await crop.keyboard.press("ArrowRight");
}

// 3) 홍보 이미지: promo.html의 장면 셋. 제목 글꼴 Jua는 빌드 자산에서 가져온다.
const jua = fs
  .readdirSync(path.join(site, "assets"))
  .find((f) => /^jua-.*\.woff2$/.test(f));
fs.copyFileSync(path.join(site, "assets", jua), path.join(work, "jua.woff2"));
fs.copyFileSync(path.join(here, "promo.html"), path.join(work, "promo.html"));
const promos = {
  tabs: "1-문법-단어",
  menu: "2-드래그-우클릭",
  mine: "3-내-일본어",
};
for (const [id, name] of Object.entries(promos)) {
  await page.goto(`file://${work}/promo.html#${id}`);
  await page.reload(); // 해시만 바뀌면 장면을 고르는 스크립트가 다시 돌지 않는다.
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}/promo/${name}.png` });
}
await browser.close();
server.close();

// 자체 확인: 7장 모두 1280×800이어야 한다.
const outputs = [
  ...Object.values(shots),
  ...Object.values(promos).map((n) => `promo/${n}`),
];
for (const name of outputs) {
  const header = fs.readFileSync(`${out}/${name}.png`).subarray(16, 24);
  const [w, h] = [header.readUInt32BE(0), header.readUInt32BE(4)];
  if (w !== 1280 || h !== 800) throw new Error(`${name}.png이 ${w}×${h}다`);
}
console.log(`${outputs.length}장 1280×800: ${out}`);
