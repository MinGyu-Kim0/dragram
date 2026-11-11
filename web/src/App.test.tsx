import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";

function open(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

/** 로그인하지 않은 채로 /를 열고 소개 페이지가 그려질 때까지 기다린다. */
async function openLanding() {
  open("/");
  await screen.findByRole("list", { name: "시작하는 방법" });
}

const footer = () => within(screen.getByRole("contentinfo"));

const ME = { email: "me@example.com", account: "42" };

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let calls: string[];
let responses: Record<string, () => Response | Promise<Response>>;

beforeEach(() => {
  calls = [];
  responses = {
    "GET /api/auth/me/": () => json({ user: null }),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const key = `${init.method ?? "GET"} ${url}`;
      calls.push(key);
      return responses[key]();
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

/** 브라우저 설정(prefers-color-scheme)을 흉내 낸다. 돌려준 함수로 설정을 바꾼다. */
function prefersDark(dark: boolean) {
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      return dark && query === "(prefers-color-scheme: dark)";
    },
    addEventListener: (_: string, listener: () => void) =>
      listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) =>
      listeners.delete(listener),
  }));
  return (next: boolean) => {
    dark = next;
    listeners.forEach((listener) => listener());
  };
}

test("고른 적이 없으면 브라우저 설정이 바뀔 때 테마 버튼도 따라 바뀐다", async () => {
  const setDark = prefersDark(false);
  await openLanding();
  const button = await screen.findByRole("button", { name: "다크 모드" });
  expect(button).toHaveAttribute("aria-pressed", "false");

  act(() => setDark(true));
  expect(button).toHaveAttribute("aria-pressed", "true");
});

test("테마 버튼은 처음에는 브라우저 설정을 따르고 고른 테마를 고정하지 않는다", async () => {
  prefersDark(true);
  await openLanding();

  expect(screen.getByRole("button", { name: "다크 모드" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(document.documentElement.dataset.theme).toBeUndefined();
});

test("테마 버튼을 누르면 반대 테마로 바뀌고 다시 열어도 유지된다", async () => {
  const user = userEvent.setup();
  prefersDark(false);
  await openLanding();

  await user.click(screen.getByRole("button", { name: "다크 모드" }));
  expect(document.documentElement.dataset.theme).toBe("dark");

  cleanup();
  await openLanding();
  expect(screen.getByRole("button", { name: "다크 모드" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("로그인했으면 /에서 소개 페이지 대신 내 기록 목록을 보인다", async () => {
  responses["GET /api/auth/me/"] = () => json({ user: ME });
  responses["GET /api/my-japanese/grammar/?state=added"] = () =>
    json({
      usages: [
        {
          usage_id: 1,
          pattern_name: "ている",
          name: "진행",
          explanation_ko: "동작이 이어진다",
          korean_equivalent: null,
          korean_equivalent_review_status: null,
          review_status: "approved",
          examples: [],
        },
      ],
    });
  open("/");

  expect(
    await screen.findByRole("list", { name: "추가한 문법" }),
  ).toHaveTextContent("진행");
  expect(
    screen.queryByRole("list", { name: "시작하는 방법" }),
  ).not.toBeInTheDocument();
});

test("로그인 확인 전에는 헤더만 보이고 소개 페이지도 홈도 그리지 않는다", async () => {
  responses["GET /api/auth/me/"] = () => new Promise<Response>(() => {});
  open("/");

  await waitFor(() => expect(calls).toContain("GET /api/auth/me/"));
  expect(screen.getByRole("banner")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("banner")).queryByRole("link", { name: "로그인" }),
  ).not.toBeInTheDocument();
});

test("로그인 후 헤더에 내 기록과 계정 메뉴가 있고, 로그아웃하면 소개 페이지로 돌아간다", async () => {
  const user = userEvent.setup();
  responses["GET /api/auth/me/"] = () => json({ user: ME });
  responses["GET /api/my-japanese/grammar/?state=added"] = () =>
    json({ usages: [] });
  responses["POST /api/auth/logout/"] = () => json({ user: null });
  open("/");
  const header = within(screen.getByRole("banner"));

  const nav = within(await header.findByRole("navigation", { name: "메뉴" }));
  expect(nav.getByRole("link", { name: "내 기록" })).toHaveAttribute(
    "href",
    "/sentences",
  );
  expect(
    header.queryByRole("link", { name: "로그인" }),
  ).not.toBeInTheDocument();

  await user.click(header.getByText("계정 메뉴"));
  expect(header.getByText("me@example.com")).toBeVisible();
  await user.click(header.getByRole("button", { name: "로그아웃" }));

  expect(
    await screen.findByRole("list", { name: "시작하는 방법" }),
  ).toBeInTheDocument();
  expect(calls).toContain("POST /api/auth/logout/");
  expect(header.getByRole("link", { name: "로그인" })).toBeInTheDocument();
});

test("내 기록에서 로그아웃해도 로그인 화면이 아니라 소개 페이지로 간다", async () => {
  const user = userEvent.setup();
  responses["GET /api/auth/me/"] = () => json({ user: ME });
  responses["GET /api/my-japanese/grammar/?state=added"] = () =>
    json({ usages: [] });
  responses["POST /api/auth/logout/"] = () => {
    // 소개 페이지가 새로 로그인 상태를 물을 때 로그아웃된 상태를 돌려준다.
    responses["GET /api/auth/me/"] = () => json({ user: null });
    return json({ user: null });
  };
  open("/sentences");
  const header = within(screen.getByRole("banner"));

  await user.click(await header.findByText("계정 메뉴"));
  await user.click(header.getByRole("button", { name: "로그아웃" }));

  expect(
    await screen.findByRole("list", { name: "시작하는 방법" }),
  ).toBeInTheDocument();
});

test("계정 메뉴는 Escape로 닫히고 포커스가 메뉴 단추로 돌아온다", async () => {
  const user = userEvent.setup();
  responses["GET /api/auth/me/"] = () => json({ user: ME });
  responses["GET /api/my-japanese/grammar/?state=added"] = () =>
    json({ usages: [] });
  open("/");
  const header = within(screen.getByRole("banner"));
  const toggle = (await header.findByText("계정 메뉴")).closest("summary")!;
  const menu = toggle.closest("details")!;

  // Enter·Space로 여는 것은 브라우저의 summary 기본 동작이라 jsdom에서는 눌러서 연다.
  await user.click(toggle);
  expect(menu).toHaveAttribute("open");
  await user.keyboard("{Escape}");
  expect(menu).not.toHaveAttribute("open");
  expect(toggle).toHaveFocus();
});

test("로그인 확인이 서버 오류로 실패해도 /sentences는 로그인 화면으로 보내지 않고 기록 오류를 보인다", async () => {
  responses["GET /api/auth/me/"] = () => json({}, 500);
  responses["GET /api/my-japanese/grammar/?state=added"] = () => json({}, 500);
  open("/sentences");

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "문법을 불러오지 못했어요",
  );
  expect(
    within(screen.getByRole("banner")).queryByRole("link", { name: "로그인" }),
  ).not.toBeInTheDocument();
});

test("로그아웃에 실패하면 로그인한 헤더를 그대로 두고 알린다", async () => {
  const user = userEvent.setup();
  responses["GET /api/auth/me/"] = () => json({ user: ME });
  responses["GET /api/my-japanese/grammar/?state=added"] = () =>
    json({ usages: [] });
  responses["POST /api/auth/logout/"] = () => json({}, 500);
  open("/");
  const header = within(screen.getByRole("banner"));

  await user.click(await header.findByText("계정 메뉴"));
  await user.click(header.getByRole("button", { name: "로그아웃" }));

  expect(await header.findByRole("alert")).toHaveTextContent(
    "로그아웃하지 못했어요",
  );
  expect(header.getByRole("navigation", { name: "메뉴" })).toBeInTheDocument();
});

test("작동 방식 보기 링크는 시작하는 방법으로 간다", async () => {
  await openLanding();

  expect(screen.getByRole("link", { name: "작동 방식 보기" })).toHaveAttribute(
    "href",
    "#how",
  );
  expect(document.getElementById("how")).toContainElement(
    screen.getByRole("list", { name: "시작하는 방법" }),
  );
});

test("사이드 패널 예시도 미검수 설명에 배지를 단다", async () => {
  await openLanding();
  const preview = screen.getByRole("figure", { name: "사이드 패널 예시" });

  // 예시도 실제 패널처럼 미검수 설명에는 배지를 단다.
  expect(within(preview).getByText("AI 생성·미검수")).toBeInTheDocument();
});

test("스토어 주소가 있으면 Chrome에 추가 링크가 그 주소로 간다", async () => {
  vi.stubEnv(
    "VITE_CHROME_WEB_STORE_URL",
    "https://chromewebstore.google.com/detail/dragram/x",
  );
  await openLanding();

  expect(screen.getByRole("link", { name: "Chrome에 추가" })).toHaveAttribute(
    "href",
    "https://chromewebstore.google.com/detail/dragram/x",
  );
});

test("스토어 주소가 없으면 준비 중으로 보이고 링크는 없다", async () => {
  vi.stubEnv("VITE_CHROME_WEB_STORE_URL", "");
  await openLanding();

  expect(
    screen.queryByRole("link", { name: "Chrome에 추가" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Chrome 웹 스토어 준비 중")).toBeInTheDocument();
});

test("푸터에 연락 메일을 보인다", async () => {
  vi.stubEnv("VITE_CONTACT_EMAIL", "contact@example.com");
  await openLanding();

  expect(
    footer().getByRole("link", { name: "contact@example.com" }),
  ).toHaveAttribute("href", "mailto:contact@example.com");
});

test("푸터 링크로 홈, 개인정보처리방침, 이용약관을 오간다", async () => {
  const user = userEvent.setup();
  await openLanding();

  await user.click(footer().getByRole("link", { name: "개인정보처리방침" }));
  expect(
    screen.getByRole("heading", { level: 1, name: "개인정보처리방침" }),
  ).toBeInTheDocument();

  await user.click(footer().getByRole("link", { name: "이용약관" }));
  expect(
    screen.getByRole("heading", { level: 1, name: "이용약관" }),
  ).toBeInTheDocument();

  await user.click(footer().getByRole("link", { name: "Dragram 홈" }));
  expect(
    screen.getByRole("list", { name: "시작하는 방법" }),
  ).toBeInTheDocument();
});

// #237 "쓰지 않을 문구"
const FORBIDDEN_PHRASES = [
  "개인정보를 수집하지 않습니다",
  "선택한 글자만 전송합니다",
  "분석 후 원문을 즉시 삭제합니다",
  "제3자에게 전달하지 않습니다",
  "AI 학습에 쓰이지 않으므로 저장되지 않습니다",
  "운영자는 데이터를 볼 수 없습니다",
  "확장을 삭제하면 서버 데이터도 삭제됩니다",
  "나이 제한이 없",
];

test.each([
  "/privacy",
  "/privacy/2026-11-04",
  "/privacy/2026-11-02",
  "/privacy/2026-10-29",
])("%s는 로그인 없이 처리방침을 보여준다", (path) => {
  open(path);

  expect(
    screen.getByRole("heading", { level: 1, name: "개인정보처리방침" }),
  ).toBeInTheDocument();
});

test("최신 처리방침은 확장 연결에 확장 프로그램 버전을 적는다(#349)", () => {
  open("/privacy");

  const row = screen.getByRole("rowheader", {
    name: "확장 프로그램 연결",
  }).parentElement!;
  expect(row).toHaveTextContent("마지막으로 요청한 확장 프로그램 버전");
  expect(row).toHaveTextContent("업데이트가 필요한지 확인·안내");
});

test("처리방침에 쓰지 않을 문구가 없다", () => {
  open("/privacy");

  for (const phrase of FORBIDDEN_PHRASES) {
    expect(screen.getByRole("main")).not.toHaveTextContent(phrase);
  }
});

test("처리방침 표는 첫 열을 행 제목으로 읽고, 넓은 표는 키보드로 스크롤할 수 있다", () => {
  open("/privacy");

  expect(
    screen.getByRole("rowheader", { name: "Google 로그인" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("columnheader", { name: "법적 근거" }),
  ).toBeInTheDocument();
  const scroller = screen.getByRole("region", { name: "국외이전 안내 표" });
  expect(scroller).toHaveAttribute("tabindex", "0");
  expect(within(scroller).getByRole("table")).toBeInTheDocument();
});

test("운영자가 확인하기 전인 값은 그럴듯한 값 대신 확인 필요 자리로 보인다", () => {
  vi.stubEnv("VITE_CONTACT_EMAIL", "");
  vi.stubEnv("VITE_PRIVACY_OFFICER", "");
  open("/privacy");

  for (const value of ["운영자 실명"]) {
    expect(screen.getAllByText(`확인 필요: ${value}`).length).toBeGreaterThan(
      0,
    );
  }
  expect(screen.queryByRole("link", { name: /@/ })).not.toBeInTheDocument();
  expect(screen.getAllByText("연락처 준비 중").length).toBeGreaterThan(0);
});

test("연락처와 보호책임자가 정해지면 메일 링크와 이름을 보인다", () => {
  vi.stubEnv("VITE_CONTACT_EMAIL", "privacy@example.com");
  vi.stubEnv("VITE_PRIVACY_OFFICER", "홍길동");
  open("/privacy");

  expect(
    screen.getAllByRole("link", { name: "privacy@example.com" })[0],
  ).toHaveAttribute("href", "mailto:privacy@example.com");
  expect(
    screen.getByRole("region", {
      name: "14. 개인정보 보호책임자와 외부 상담 창구",
    }),
  ).toHaveTextContent("홍길동");
});

test("이전 버전 목록은 버전별 주소로 연결된다", () => {
  open("/privacy");

  expect(
    within(
      screen.getByRole("region", {
        name: "15. 처리방침이 바뀌면 어떻게 알리나요?",
      }),
    ).getByRole("link", { name: "2026년 10월 29일 시행" }),
  ).toHaveAttribute("href", "/privacy/2026-10-29");
});

test("없는 버전 주소는 최신 처리방침으로 안내한다", () => {
  open("/privacy/2020-01-01");

  expect(
    screen.getByText("2020-01-01에 시행한 개인정보처리방침은 없습니다."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "최신 개인정보처리방침 보기" }),
  ).toHaveAttribute("href", "/privacy");
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

test.each(["/terms", "/terms/2026-11-02"])(
  "%s는 로그인 없이 약관을 보여준다",
  (path) => {
    open(path);

    expect(
      screen.getByRole("heading", { level: 1, name: "이용약관" }),
    ).toBeInTheDocument();
  },
);

test("약관의 운영자 이름은 처리방침과 같은 설정값을 쓴다", () => {
  vi.stubEnv("VITE_PRIVACY_OFFICER", "");
  open("/terms");
  expect(screen.getByText("확인 필요: 운영자 이름")).toBeInTheDocument();
});

// 처리방침과 약관은 합니다체로 쓴다. '~해 주세요' 같은 요청 표현과 '~나요?' 같은 질문형 절
// 제목(처리방침 초안)만 해요체를 허용한다.
test.each(["/privacy", "/terms", "/privacy/2020-01-01", "/terms/2020-01-01"])(
  "%s는 합니다체로 쓴다",
  (path) => {
    open(path);

    const endings = screen
      .getByRole("main")
      .textContent!.match(/[^세]요[.!)]/g);
    expect(endings).toBeNull();
  },
);

test("없는 약관 버전 주소는 최신 약관으로 안내한다", () => {
  open("/terms/2020-01-01");

  expect(
    screen.getByText("2020-01-01에 시행한 이용약관은 없습니다."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "최신 이용약관 보기" }),
  ).toHaveAttribute("href", "/terms");
});
