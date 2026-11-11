import { defineConfig } from "@playwright/test";

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
