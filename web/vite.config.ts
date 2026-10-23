import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 웹과 API를 같은 출처로 둔다(Django 세션·CSRF). Host 헤더를 그대로 넘겨 Django의 CSRF
    // 출처 검사가 웹 출처와 맞게 한다.
    proxy: {
      "/api": process.env.API_PROXY_TARGET ?? "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
