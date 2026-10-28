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

const POLICY_SECTIONS = [
  "운영주체와 시행일",
  "처리하는 정보와 목적",
  "공용 분석과 내 기록",
  "처리위탁과 국외이전",
  "보유기간",
  "삭제와 탈퇴",
  "권리행사",
  "운영자가 원문을 보는 경우",
  "어린이 이용자",
  "민감한 내용은 분석하지 마세요",
  "개인정보 보호책임자와 도움받을 곳",
  "변경 안내와 이전 버전",
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
];

test.each(["/privacy", "/privacy/2026-10-28"])(
  "%s는 로그인 없이 처리방침의 모든 절을 보여준다",
  (path) => {
    open(path);

    expect(
      screen.getByRole("heading", { level: 1, name: "개인정보처리방침" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent(
      "시행일: 2026년 10월 28일",
    );
    for (const name of POLICY_SECTIONS) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
  },
);

test("처리방침은 보내는 범위, 위탁, 보관, 탈퇴를 실제 동작대로 적고 쓰지 않을 문구가 없다", () => {
  open("/privacy");
  const section = (name: string) => screen.getByRole("region", { name });

  expect(section("처리하는 정보와 목적")).toHaveTextContent(
    "드래그한 부분을 포함한 문장 전체",
  );
  expect(section("처리위탁과 국외이전")).toHaveTextContent("OpenAI");
  expect(section("처리위탁과 국외이전")).toHaveTextContent(
    "이메일은 보내지 않아요",
  );
  expect(section("공용 분석과 내 기록")).toHaveTextContent("본인만");
  expect(section("삭제와 탈퇴")).toHaveTextContent("회원 탈퇴");
  expect(section("삭제와 탈퇴")).toHaveTextContent(
    "확장 프로그램을 지워도 서버의 기록은 지워지지 않아요",
  );
  for (const phrase of FORBIDDEN_PHRASES) {
    expect(screen.getByRole("main")).not.toHaveTextContent(phrase);
  }
});

test("운영자가 확인하기 전인 값은 그럴듯한 값 대신 확인 필요 자리로 보인다", () => {
  vi.stubEnv("VITE_CONTACT_EMAIL", "");
  vi.stubEnv("VITE_PRIVACY_OFFICER", "");
  open("/privacy");

  for (const value of [
    "OpenAI 데이터 공유 설정",
    "OpenAI 계약 법인",
    "OpenAI 처리 국가",
    "서버 접속 기록 보관 기간",
    "서버 스냅샷·DB 백업 보관 기간",
    "운영자 이름",
  ]) {
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
    screen.getByRole("region", { name: "개인정보 보호책임자와 도움받을 곳" }),
  ).toHaveTextContent("홍길동");
});

test("이전 버전 목록은 버전별 주소로 연결된다", () => {
  open("/privacy");

  expect(
    within(
      screen.getByRole("region", { name: "변경 안내와 이전 버전" }),
    ).getByRole("link", { name: "2026년 10월 28일 시행" }),
  ).toHaveAttribute("href", "/privacy/2026-10-28");
});

test("없는 버전 주소는 최신 처리방침으로 안내한다", () => {
  open("/privacy/2020-01-01");

  expect(
    screen.getByText("2020-01-01에 시행한 개인정보처리방침은 없어요."),
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

test.each(["/terms", "/terms/2026-10-28"])(
  "%s는 로그인 없이 약관의 모든 절을 처리방침과 같은 시행일로 보여준다",
  (path) => {
    open(path);

    expect(screen.getByRole("main")).toHaveTextContent(
      "시행일: 2026년 10월 28일",
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
  expect(section("사용량 한도")).toHaveTextContent("그날 한도는 이어져요");
  expect(section("입력한 글과 공용 분석")).toHaveTextContent(
    "원문은 공용으로 저장하지 않아요",
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
      name: "2026년 10월 28일 시행",
    }),
  ).toHaveAttribute("href", "/terms/2026-10-28");
});

test("약관의 운영자 이름은 처리방침과 같은 설정값을 쓴다", () => {
  vi.stubEnv("VITE_PRIVACY_OFFICER", "");
  open("/terms");
  expect(screen.getByText("확인 필요: 운영자 이름")).toBeInTheDocument();
});

test("없는 약관 버전 주소는 최신 약관으로 안내한다", () => {
  open("/terms/2020-01-01");

  expect(
    screen.getByText("2020-01-01에 시행한 이용약관은 없어요."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "최신 이용약관 보기" }),
  ).toHaveAttribute("href", "/terms");
});
