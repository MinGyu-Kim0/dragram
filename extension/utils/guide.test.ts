import { beforeEach, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { openGuideOnInstall } from "./guide";

beforeEach(() => {
  fakeBrowser.reset();
});

test("처음 설치하면 가이드를 새 탭으로 연다", async () => {
  const create = vi.spyOn(fakeBrowser.tabs, "create");

  await openGuideOnInstall("install");

  expect(create).toHaveBeenCalledWith({
    url: fakeBrowser.runtime.getURL("/guide.html"),
  });
});

test("업데이트할 때는 가이드를 열지 않는다", async () => {
  const create = vi.spyOn(fakeBrowser.tabs, "create");

  await openGuideOnInstall("update");

  expect(create).not.toHaveBeenCalled();
});
