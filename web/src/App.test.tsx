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

test("홈은 로그인 없이 소개, 세 단계, 자주 묻는 질문을 보여준다", async () => {
  await openLanding();

  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "읽다가 막힌 일본어 문장, 드래그하면 문법이 보여요",
  );
  expect(screen.getByRole("link", { name: "작동 방식 보기" })).toHaveAttribute(
    "href",
    "#how",
  );
  expect(document.getElementById("how")).toContainElement(
    screen.getByRole("list", { name: "시작하는 방법" }),
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

test("헤더에 로고와 로그인 링크가 있다", async () => {
  await openLanding();
  const header = within(screen.getByRole("banner"));

  expect(header.getByRole("link", { name: "Dragram" })).toHaveAttribute(
    "href",
    "/",
  );
  expect(header.getByRole("link", { name: "로그인" })).toHaveAttribute(
    "href",
    "/connect",
  );
});

test("사이드 패널 예시는 일본어 예문, 번역, 문법 카드를 보여준다", async () => {
  await openLanding();
  const preview = screen.getByRole("figure", { name: "사이드 패널 예시" });

  expect(preview.querySelector('[lang="ja"]')).toHaveTextContent(
    "忙しくても、毎朝本を読むようにしています。",
  );
  expect(
    within(preview).getByText("바빠도 매일 아침 책을 읽으려고 하고 있어요."),
  ).toBeInTheDocument();
  expect(within(preview).getByText("~하도록 하고 있다")).toBeInTheDocument();
  // 예시도 실제 패널처럼 미검수 설명에는 배지를 단다.
  expect(within(preview).getByText("AI 생성·미검수")).toBeInTheDocument();
});

test("자주 묻는 질문은 질문을 눌러 답을 펼친다", async () => {
  const user = userEvent.setup();
  await openLanding();
  const question = screen.getByText("분석에 AI를 쓰나요?");
  const item = question.closest("details");

  expect(item).not.toHaveAttribute("open");
  await user.click(question);
  expect(item).toHaveAttribute("open");
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

test("푸터에 글꼴 라이선스를 밝힌다", async () => {
  await openLanding();

  expect(screen.getByRole("contentinfo")).toHaveTextContent(
    "글꼴: Jua, IBM Plex Sans KR, Zen Maru Gothic (SIL OFL 1.1)",
  );
  expect(footer().getByRole("link", { name: "SIL OFL 1.1" })).toHaveAttribute(
    "href",
    "https://openfontlicense.org/",
  );
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

// #253의 운영자 검토 초안에서 옮긴 절
const POLICY_SECTIONS = [
  "먼저 알아두세요",
  "1. 어떤 정보를 왜 처리하나요?",
  "2. 문장은 언제, 어디로 전송되나요?",
  "3. 내 기록과 공용 분석 결과는 어떻게 다른가요?",
  "4. AI는 정보를 어떻게 사용하나요?",
  "5. 다른 업체와 정보를 주고받나요?",
  "6. 개인정보가 국외로 이전되나요?",
  "7. 얼마나 보관하나요?",
  "8. 어떻게 삭제하고 파기하나요?",
  "9. 열람·정정·삭제·처리정지는 어떻게 요청하나요?",
  "10. 쿠키와 브라우저 저장소를 사용하나요?",
  "11. 개인정보를 어떻게 보호하나요?",
  "12. 아동의 개인정보는 어떻게 처리하나요?",
  "13. 민감한 내용과 자동 처리에 관한 안내",
  "14. 개인정보 보호책임자와 외부 상담 창구",
  "15. 처리방침이 바뀌면 어떻게 알리나요?",
];

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

test.each(["/privacy", "/privacy/2026-11-01", "/privacy/2026-10-29"])(
  "%s는 로그인 없이 처리방침의 모든 절을 보여준다",
  (path) => {
    open(path);

    expect(
      screen.getByRole("heading", { level: 1, name: "개인정보처리방침" }),
    ).toBeInTheDocument();
    for (const name of POLICY_SECTIONS) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
  },
);

test("처리방침은 보내는 범위, 위탁, 보관, 탈퇴, 연령을 실제 동작대로 적고 쓰지 않을 문구가 없다", () => {
  open("/privacy");
  const section = (name: string) => screen.getByRole("region", { name });

  expect(section("먼저 알아두세요")).toHaveTextContent(
    "선택한 부분을 포함하는 문장 전체가 서버로 전송됩니다",
  );
  expect(section("6. 개인정보가 국외로 이전되나요?")).toHaveTextContent(
    "OpenAI",
  );
  expect(section("4. AI는 정보를 어떻게 사용하나요?")).toHaveTextContent(
    "계정 이메일과 Google 계정 식별자를 AI 요청의 별도 항목으로 보내지는 않습니다",
  );
  // #252: 탈퇴 당일 사용량은 토큰 수·시각과 비교값만, 매일 정리
  expect(section("7. 얼마나 보관하나요?")).toHaveTextContent(
    "분석 식별자·모델·재시도 횟수는 비움",
  );
  // #196: 내 기록 화면에서 문장별 확인·삭제
  expect(
    section("9. 열람·정정·삭제·처리정지는 어떻게 요청하나요?"),
  ).toHaveTextContent("내 기록");
  expect(
    section("9. 열람·정정·삭제·처리정지는 어떻게 요청하나요?"),
  ).toHaveTextContent("회원 탈퇴");
  // #251: 만 14세 이상만 가입
  expect(section("12. 아동의 개인정보는 어떻게 처리하나요?")).toHaveTextContent(
    "만 14세 이상만 가입",
  );
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

test("운영자가 확인한 값은 확인 필요 대신 확정 문구로 적는다", () => {
  open("/privacy");
  const main = screen.getByRole("main");

  for (const fact of [
    "OpenAI OpCo, LLC",
    "Amazon Web Services Korea LLC",
    "Google LLC",
    "데이터 공유에 참여하지 않습니다",
    "gpt-6-luna",
    "최대 30MB",
    "2주",
    "최대 7일",
    "처리 완료 후 1년",
    "이메일로만",
    "이용약관에 동의한 시각",
    "안내한 처리방침의 버전",
    "최대 24시간",
    "SSH 키로만",
    "운영자 한 명",
    "다른 사람의 이름이 들어 있더라도",
    "연령별 콘텐츠 필터를 두지 않습니다",
    "제15조제1항제6호",
    "서비스를 종료하면 파기합니다",
    "서버 접속 기록을 3개월 보관합니다",
  ]) {
    expect(main).toHaveTextContent(fact);
  }
  for (const resolved of [
    "매일 정리 예약 작업 등록",
    "OpenAI 데이터 공유 설정",
    "서버 접속·오류 기록 보관기간과 삭제 주기",
    "백업 여부, 대상, 장소, 보관기간 및 삭제 반영 시점",
    "실제 운영 사이트에서 해당 기능 제공·동작 여부",
    "gpt-6-luna의 프롬프트 캐시 보관 조건",
    "AWS 지원 과정의 국외 조회 여부",
    "문장에 포함된 이용자 외 사람의 개인정보와 민감정보를 처리하는 근거",
    "실제 위탁계약의 목적·범위·보호조치·재위탁 조건, 수탁자 관리·감독 절차, Dragram에 적용되는 재수탁자 목록",
    "실제 계약·처리 범위가 이 요건을 충족하는지",
    "서버 본 디스크의 저장 시 암호화 여부",
    "만 14~17세 미성년 이용자에 대해 OpenAI의 미성년자 보호·데이터 보관 조건을 충족하는 방식",
    "실제 게시·시행일",
    "탈퇴 후 보관의 법적 근거와 필요한 최소 항목",
    "탈퇴 후 보관의 근거",
    "개인정보가 포함된 공용 결과의 보유기간, 재사용의 적법한 근거, 삭제 요청 시 재사용 중단·삭제 절차",
    "구체적 보유기간 또는 종료 기준, 개인정보 포함 결과의 삭제 기준",
    "Dragram에 실제로 적용되는 법정 보존 의무",
  ]) {
    expect(main).not.toHaveTextContent(`확인 필요: ${resolved}`);
  }
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

const TERMS_SECTIONS = [
  "운영자와 적용 범위",
  "서비스 범위",
  "계정",
  "사용량 한도",
  "AI가 만든 내용의 한계",
  "입력한 글과 공용 분석",
  "권리 침해와 개인정보 신고",
  "단어 정보의 출처",
  "이용자가 하지 않을 일",
  "이용 제한과 이의 제기",
  "서비스 변경과 중단",
  "책임 범위",
  "약관 변경",
  "준거법",
  "개인정보와 문의",
];

test.each(["/terms", "/terms/2026-11-01"])(
  "%s는 로그인 없이 약관의 모든 절을 처리방침과 같은 시행일로 보여준다",
  (path) => {
    open(path);

    expect(screen.getByRole("main")).toHaveTextContent(
      "시행일: 2026년 11월 1일",
    );
    for (const name of TERMS_SECTIONS) {
      expect(
        screen.getByRole("heading", { level: 2, name }),
      ).toBeInTheDocument();
    }
  },
);

test("약관은 결정한 제한·재사용·책임·변경 절차를 적는다", () => {
  open("/terms");
  const section = (name: string) => screen.getByRole("region", { name });

  expect(section("서비스 범위")).toHaveTextContent("무료");
  expect(section("사용량 한도")).toHaveTextContent("그날 한도는 이어집니다");
  expect(section("입력한 글과 공용 분석")).toHaveTextContent(
    "분석한 문장의 원문을 저장하지 않습니다",
  );
  expect(section("입력한 글과 공용 분석")).toHaveTextContent(
    "예문으로 저장하기로 직접 고른 문장만",
  );
  expect(section("계정")).toHaveTextContent("만 14세 이상");
  expect(section("계정")).toHaveTextContent("14세 미만");
  expect(section("권리 침해와 개인정보 신고")).toHaveTextContent("공용 분석");
  expect(section("권리 침해와 개인정보 신고")).toHaveTextContent("누구나");
  expect(section("이용 제한과 이의 제기")).toHaveTextContent(
    "경고 없이 바로 정지",
  );
  expect(section("이용 제한과 이의 제기")).toHaveTextContent(
    "정지된 상태에서도",
  );
  expect(section("책임 범위")).toHaveTextContent("고의나 중대한 과실");
  expect(section("약관 변경")).toHaveTextContent("7일 전");
  expect(section("약관 변경")).toHaveTextContent("30일 전");
  expect(section("준거법")).toHaveTextContent("대한민국 법");
  expect(
    within(section("개인정보와 문의")).getByRole("link", {
      name: "개인정보처리방침",
    }),
  ).toHaveAttribute("href", "/privacy");
  expect(
    within(section("이전 버전")).getByRole("link", {
      name: "2026년 10월 29일 시행",
    }),
  ).toHaveAttribute("href", "/terms/2026-10-29");
});

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
