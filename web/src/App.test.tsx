import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import App from "./App";

function open(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

const footer = () => within(screen.getByRole("contentinfo"));

afterEach(() => {
  vi.unstubAllEnvs();
});

test("홈은 로그인 없이 소개, 세 단계, 자주 묻는 질문을 보여준다", () => {
  open("/");

  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "Dragram",
  );
  expect(
    within(screen.getByRole("list", { name: "시작하는 방법" })).getAllByRole(
      "listitem",
    ),
  ).toHaveLength(3);
  expect(
    screen.getByRole("heading", { name: "자주 묻는 질문" }),
  ).toBeInTheDocument();
});

test("스토어 주소가 있으면 Chrome에 추가 링크가 그 주소로 간다", () => {
  vi.stubEnv(
    "VITE_CHROME_WEB_STORE_URL",
    "https://chromewebstore.google.com/detail/dragram/x",
  );
  open("/");

  expect(screen.getByRole("link", { name: "Chrome에 추가" })).toHaveAttribute(
    "href",
    "https://chromewebstore.google.com/detail/dragram/x",
  );
});

test("스토어 주소가 없으면 준비 중으로 보이고 링크는 없다", () => {
  vi.stubEnv("VITE_CHROME_WEB_STORE_URL", "");
  open("/");

  expect(
    screen.queryByRole("link", { name: "Chrome에 추가" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Chrome 웹 스토어 준비 중")).toBeInTheDocument();
});

test("푸터 링크로 홈, 개인정보처리방침, 이용약관을 오간다", async () => {
  const user = userEvent.setup();
  open("/");

  await user.click(footer().getByRole("link", { name: "개인정보처리방침" }));
  expect(
    screen.getByRole("heading", { level: 1, name: "개인정보처리방침" }),
  ).toBeInTheDocument();

  await user.click(footer().getByRole("link", { name: "이용약관" }));
  expect(
    screen.getByRole("heading", { level: 1, name: "이용약관" }),
  ).toBeInTheDocument();

  await user.click(footer().getByRole("link", { name: "Dragram 홈" }));
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "Dragram",
  );
});

test("개인정보처리방침에 처리 위탁, 원문 보관, 삭제 요청 방법과 보호책임자가 있다", () => {
  vi.stubEnv("VITE_CONTACT_EMAIL", "privacy@example.com");
  vi.stubEnv("VITE_PRIVACY_OFFICER", "홍길동");
  open("/privacy");

  for (const name of [
    "수집하는 정보",
    "공용 데이터와 개인 데이터",
    "처리 위탁",
    "국외 이전",
    "보관 기간",
    "삭제 요청",
    "개인정보 보호책임자",
  ]) {
    expect(screen.getByRole("heading", { name })).toBeInTheDocument();
  }
  expect(screen.getByRole("region", { name: "처리 위탁" })).toHaveTextContent(
    "OpenAI",
  );
  expect(
    screen.getByRole("region", { name: "공용 데이터와 개인 데이터" }),
  ).toHaveTextContent("본인만");
  expect(
    screen.getAllByRole("link", { name: "privacy@example.com" })[0],
  ).toHaveAttribute("href", "mailto:privacy@example.com");
  expect(
    screen.getByRole("region", { name: "개인정보 보호책임자" }),
  ).toHaveTextContent("홍길동");
});

test("연락처가 정해지지 않았으면 빈 메일 링크 대신 준비 중 문구를 보인다", () => {
  vi.stubEnv("VITE_CONTACT_EMAIL", "");
  vi.stubEnv("VITE_PRIVACY_OFFICER", "");
  open("/privacy");

  expect(screen.queryByRole("link", { name: /@/ })).not.toBeInTheDocument();
  expect(screen.getAllByText("연락처 준비 중").length).toBeGreaterThan(0);
});

test("이용약관과 푸터에 JMdict CC BY-SA 4.0 출처가 있다", () => {
  open("/terms");

  expect(
    screen.getByRole("heading", { level: 1, name: "이용약관" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("main")).toHaveTextContent("AI 생성·미검수");
  expect(screen.getByRole("main")).toHaveTextContent("CC BY-SA 4.0");
  expect(footer().getByRole("link", { name: "JMdict" })).toHaveAttribute(
    "href",
    expect.stringContaining("edrdg.org"),
  );
  expect(footer().getByRole("link", { name: "CC BY-SA 4.0" })).toHaveAttribute(
    "href",
    "https://creativecommons.org/licenses/by-sa/4.0/",
  );
});
