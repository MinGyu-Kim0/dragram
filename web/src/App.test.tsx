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

// 운영자 검토 초안(~/privacy-policy-draft.ko.md)의 절(#253)
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

test.each(["/privacy", "/privacy/2026-10-28"])(
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
    "토큰 수와 시각, 비교값만",
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

test("운영자가 확인하기 전인 값은 그럴듯한 값 대신 확인 필요 자리로 보인다", () => {
  vi.stubEnv("VITE_CONTACT_EMAIL", "");
  vi.stubEnv("VITE_PRIVACY_OFFICER", "");
  open("/privacy");

  for (const value of [
    "운영자 실명",
    "OpenAI 데이터 공유 설정",
    "OpenAI 계약 법인명과 개인정보 문의 연락처",
    "OpenAI 처리 국가(추론·보관·지원·재위탁 포함 전체)",
    "서버 접속·오류 기록 보관기간",
    "백업 여부, 대상, 장소, 보관기간",
    "매일 정리 예약 작업 등록",
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
