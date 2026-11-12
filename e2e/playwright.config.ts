import { defineConfig } from "@playwright/test";
import { readdirSync } from "node:fs";

// 설정을 바꾼 스택(stacks/<이름>.yaml). 그 스택의 시나리오는 이름 태그(@<이름>)를 단다.
// run.sh(e2e/stacks/*.yaml)와 같은 파일만 센다.
const stacks = readdirSync(new URL("stacks", import.meta.url))
  .filter((file) => file.endsWith(".yaml"))
  .map((file) => file.replace(/\.yaml$/, ""));

// run.sh가 compose 스택을 띄운 뒤 e2e 컨테이너 안에서 돈다(support/in-container.sh).
export default defineConfig({
  testDir: "tests",
  // 시나리오가 한 스택(DB·작업자)을 함께 쓰므로 하나씩 돈다.
  workers: 1,
  // 실제 OpenAI 응답을 기다린다.
  timeout: 180_000,
  expect: { timeout: 90_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: { trace: "retain-on-failure", screenshot: "only-on-failure" },
  // 스택마다 프로젝트 하나. run.sh가 스택을 띄우고 그 프로젝트만 돌린다. 결과도 스택마다 따로 둔다.
  projects: [
    {
      name: "default",
      grepInvert: new RegExp(stacks.map((name) => `@${name}\\b`).join("|")),
      outputDir: "test-results/default",
    },
    ...stacks.map((name) => ({
      name,
      grep: new RegExp(`@${name}\\b`),
      outputDir: `test-results/${name}`,
    })),
  ],
  // 스택이 뜰 때까지 기다린다. 포트 잇기는 support/forward.mjs.
  webServer: [
    {
      command: "node support/forward.mjs 8000 backend",
      url: "http://localhost:8000/api/health/",
      timeout: 180_000,
    },
    {
      command: "node support/forward.mjs 5173 web",
      url: "http://localhost:5173/",
      timeout: 180_000,
    },
  ],
});
