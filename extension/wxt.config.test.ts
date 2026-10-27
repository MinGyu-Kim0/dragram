import { afterEach, expect, test, vi } from "vitest";

async function manifest() {
  vi.resetModules();
  const { default: config } = await import("./wxt.config");
  return config.manifest as Record<string, unknown>;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

test("스토어 빌드는 운영 주소만 쓰고 개발용 key를 넣지 않는다", async () => {
  vi.stubEnv("DRAGRAM_STORE", "true");
  vi.stubEnv("WXT_API_BASE_URL", "https://dragram.app");
  vi.stubEnv("WXT_WEB_ORIGIN", "https://dragram.app");

  const m = await manifest();

  expect(m).not.toHaveProperty("key");
  expect(m.host_permissions).toEqual(["https://dragram.app/*"]);
  expect(m.externally_connectable).toEqual({
    matches: ["https://dragram.app/*"],
  });
});

test("스토어 빌드인데 운영 주소가 아니면 빌드를 멈춘다", async () => {
  vi.stubEnv("DRAGRAM_STORE", "true");
  vi.stubEnv("WXT_API_BASE_URL", "http://localhost:8000");

  await expect(manifest()).rejects.toThrow("https://");
});

test("개발 빌드는 로컬 주소와 개발용 key를 쓴다", async () => {
  vi.stubEnv("DRAGRAM_STORE", "");
  vi.stubEnv("WXT_API_BASE_URL", undefined);
  vi.stubEnv("WXT_WEB_ORIGIN", undefined);
  const m = await manifest();

  expect(m).toHaveProperty("key");
  expect(m.host_permissions).toEqual(["http://localhost:8000/*"]);
});
