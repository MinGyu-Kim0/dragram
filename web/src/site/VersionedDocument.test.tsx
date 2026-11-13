import { render, screen } from "@testing-library/react";
import { lazy } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { json, stubFetch } from "../test-support";
import VersionedDocument, { type Version } from "./VersionedDocument";

beforeEach(() => {
  stubFetch({ "GET /api/auth/me/": () => json({ user: null }) }, () => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function openVersion(versions: Version[], version: string) {
  render(
    <MemoryRouter initialEntries={[`/doc/${version}`]}>
      <Routes>
        <Route
          path="/doc/:version"
          element={
            <VersionedDocument
              title="문서"
              path="doc"
              versions={versions}
              changeTitle="이전 버전"
            />
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

// 배포 뒤 옛 판 묶음 파일이 사라지면 늦게 불러오기가 실패한다(#422). 화면 전체가 비지 않게 한다.
test("옛 판 본문을 불러오지 못하면 안내를 보이고 다른 판으로 갈 수 있다", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const versions: Version[] = [
    { effective: "2026-11-02", Body: () => <p>최신 본문</p> },
    {
      effective: "2026-10-29",
      Body: lazy(() => Promise.reject(new Error("묶음 없음"))),
    },
  ];

  openVersion(versions, "2026-10-29");

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "본문을 불러오지 못했습니다. 페이지를 새로 고쳐 주세요.",
  );
  expect(
    screen.getByRole("link", { name: "2026년 11월 2일 시행" }),
  ).toHaveAttribute("href", "/doc/2026-11-02");
});
