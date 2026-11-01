import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import ConnectPage from "./ConnectPage";

type Call = {
  url: string;
  method: string;
  headers: Record<string, string>;
  body?: string;
};

let calls: Call[];
let responses: Record<string, () => Response>;
let googleCallback: ((response: { credential: string }) => void) | undefined;
const renderButton = vi.fn();

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  calls = [];
  document.cookie = "csrftoken=csrf-value";
  responses = { "GET /api/auth/me/": () => json({ user: null }) };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({
        url,
        method,
        headers: (init.headers ?? {}) as Record<string, string>,
        body: init.body as string | undefined,
      });
      return responses[`${method} ${url}`]();
    }),
  );
  vi.stubGlobal("google", {
    accounts: {
      id: {
        initialize: (config: {
          callback: (r: { credential: string }) => void;
        }) => {
          googleCallback = config.callback;
        },
        renderButton,
      },
    },
  });
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "web-client-id");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  renderButton.mockClear();
});

test("로그인 전에는 Google 로그인 버튼을 보인다", async () => {
  render(<ConnectPage />);

  expect(
    await screen.findByRole("heading", { name: "Dragram에 로그인" }),
  ).toBeInTheDocument();
  // 버튼은 Google 스크립트를 불러온 뒤에 그린다.
  await waitFor(() => expect(renderButton).toHaveBeenCalledTimes(1));
  expect(
    screen.queryByRole("button", { name: "로그아웃" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("Google이 준 ID 토큰을 CSRF 값과 함께 보내고 로그인한 계정을 보인다", async () => {
  responses["POST /api/auth/google/"] = () =>
    json({ user: { email: "me@example.com" } });
  render(<ConnectPage />);
  await screen.findByRole("heading", { name: "Dragram에 로그인" });

  await act(async () => googleCallback!({ credential: "google-id-token" }));

  expect(await screen.findByText("me@example.com")).toBeInTheDocument();
  const login = calls.find((c) => c.url === "/api/auth/google/")!;
  expect(login.method).toBe("POST");
  expect(login.headers["X-CSRFToken"]).toBe("csrf-value");
  expect(JSON.parse(login.body!)).toEqual({ credential: "google-id-token" });
});

describe("가입 화면(#257)", () => {
  beforeEach(() => {
    responses["POST /api/auth/google/"] = () =>
      json({ user: null, signup: { email: "me@example.com", id: "signup-1" } });
    responses["POST /api/auth/signup/"] = () =>
      json({ user: { email: "me@example.com", account: "42" } });
  });

  async function reachSignup() {
    // 가입 화면은 처리방침·약관 본문(앱 안 링크 포함)을 그리므로 라우터 안에서 띄운다.
    render(<ConnectPage />, { wrapper: MemoryRouter });
    await screen.findByRole("heading", { name: "Dragram에 로그인" });
    // 이 화면의 Google 버튼을 그린 뒤에야 콜백이 이 화면 것이다(앞 테스트의 콜백이 남아 있다).
    await waitFor(() => expect(renderButton).toHaveBeenCalledTimes(1));
    await act(async () => googleCallback!({ credential: "google-id-token" }));
    await screen.findByRole("heading", { name: "거의 다 됐어요" });
  }

  test("처음 로그인하면 가입 화면을 보이고, 약관에 체크해야 가입할 수 있다", async () => {
    await reachSignup();

    // 가입할 Google 계정을 따로 묶어 보인다(#269).
    expect(screen.getByText("Google 계정")).toBeInTheDocument();
    expect(screen.getByText("me@example.com")).toBeInTheDocument();
    const join = screen.getByRole("button", { name: "가입하기" });
    expect(join).toBeDisabled();

    await userEvent.click(
      screen.getByRole("checkbox", { name: "이용약관에 동의해요" }),
    );
    await userEvent.click(join);

    expect(
      await screen.findByRole("heading", { name: "로그인했어요" }),
    ).toBeInTheDocument();
    const signup = calls.find((c) => c.url === "/api/auth/signup/")!;
    expect(signup.method).toBe("POST");
    expect(signup.headers["X-CSRFToken"]).toBe("csrf-value");
    // 화면에 보인 가입을 함께 보내, 그사이 다른 탭에서 바뀐 계정으로 가입하지 않게 한다.
    expect(JSON.parse(signup.body!)).toEqual({
      agree_terms: true,
      signup: "signup-1",
    });
  });

  test("약관 체크는 키보드로도 켜고 끌 수 있다", async () => {
    await reachSignup();
    const agree = screen.getByRole("checkbox", { name: "이용약관에 동의해요" });

    agree.focus();
    await userEvent.keyboard(" ");

    expect(agree).toBeChecked();
    expect(screen.getByRole("button", { name: "가입하기" })).toBeEnabled();
  });

  test("처리방침(위)과 이용약관(아래) 본문을 가입 화면에서 바로 보이고, 동의 체크는 이용약관 하나다", async () => {
    await reachSignup();

    const privacy = screen.getByRole("region", { name: "개인정보처리방침" });
    const terms = screen.getByRole("region", { name: "이용약관" });
    expect(
      within(privacy).getByRole("heading", { name: "Google 로그인" }),
    ).toBeInTheDocument();
    expect(
      within(terms).getByRole("heading", { name: "사용량 한도" }),
    ).toBeInTheDocument();
    expect(
      privacy.compareDocumentPosition(terms) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // 서버가 기록하는 판(2026-11-02)과 같은 시행일을 보인다.
    expect(within(privacy).getByText("2026년 11월 2일 시행")).toBeVisible();
    expect(within(terms).getByText("2026년 11월 2일 시행")).toBeVisible();
    // 처리방침은 동의받지 않는다. 체크는 이용약관 하나다.
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(screen.queryByText(/처리방침에 동의/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Dragram은 만 14세 이상만 쓸 수 있어요."),
    ).toBeInTheDocument();
  });

  test("문서 칸 안의 링크는 새 탭으로 열어 가입 화면을 그대로 둔다", async () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    await reachSignup();
    const terms = screen.getByRole("region", { name: "이용약관" });

    await userEvent.click(
      within(terms).getAllByRole("link", { name: "개인정보처리방침" })[0],
    );

    expect(open).toHaveBeenCalledWith("/privacy", "_blank", "noopener");
    expect(
      screen.getByRole("heading", { name: "거의 다 됐어요" }),
    ).toBeInTheDocument();
  });

  test("취소하면 아무것도 보내지 않고 로그인 카드로 돌아간다", async () => {
    await reachSignup();

    await userEvent.click(screen.getByRole("button", { name: "취소" }));

    expect(
      await screen.findByRole("heading", { name: "Dragram에 로그인" }),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/auth/signup/")).toBe(false);
  });

  test("가입을 기다린 시간이 지났으면 다시 로그인하라고 안내한다", async () => {
    responses["POST /api/auth/signup/"] = () =>
      json({ error: "AUTH:SIGNUP_EXPIRED" }, 401);
    await reachSignup();

    await userEvent.click(
      screen.getByRole("checkbox", { name: "이용약관에 동의해요" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "가입하기" }));

    expect(
      await screen.findByRole("heading", { name: "Dragram에 로그인" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "가입 시간이 지났어요. 다시 로그인해 주세요.",
    );
  });

  test("다른 탭에서 다른 계정으로 로그인해 가입이 바뀌었으면 다시 로그인하라고 안내한다", async () => {
    responses["POST /api/auth/signup/"] = () =>
      json({ error: "AUTH:ACCOUNT_MISMATCH" }, 409);
    await reachSignup();

    await userEvent.click(
      screen.getByRole("checkbox", { name: "이용약관에 동의해요" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "가입하기" }));

    expect(
      await screen.findByRole("heading", { name: "Dragram에 로그인" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "다른 탭에서 다른 계정으로 로그인했어요. 가입할 계정으로 다시 로그인해 주세요.",
    );
  });

  test("가입하지 못하면 가입 화면에서 다시 시도하게 한다", async () => {
    responses["POST /api/auth/signup/"] = () => json({}, 500);
    await reachSignup();

    await userEvent.click(
      screen.getByRole("checkbox", { name: "이용약관에 동의해요" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "가입하기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "가입하지 못했어요. 다시 시도해 주세요.",
    );
    expect(screen.getByRole("button", { name: "가입하기" })).toBeEnabled();
  });
});

test("로그인한 상태면 이메일과 로그아웃을 보이고, 로그아웃하면 로그인 버튼으로 돌아간다", async () => {
  responses["GET /api/auth/me/"] = () =>
    json({ user: { email: "me@example.com" } });
  responses["POST /api/auth/logout/"] = () => json({ user: null });
  render(<ConnectPage />);

  expect(await screen.findByText("me@example.com")).toBeInTheDocument();
  expect(renderButton).not.toHaveBeenCalled();

  await userEvent.click(screen.getByRole("button", { name: "로그아웃" }));

  expect(
    await screen.findByRole("heading", { name: "Dragram에 로그인" }),
  ).toBeInTheDocument();
  const logout = calls.find((c) => c.url === "/api/auth/logout/")!;
  expect(logout.headers["X-CSRFToken"]).toBe("csrf-value");
});

describe("회원 탈퇴(#239)", () => {
  beforeEach(() => {
    responses["GET /api/auth/me/"] = () =>
      json({ user: { email: "me@example.com", account: "42" } });
    responses["POST /api/auth/withdraw/"] = () => json({ user: null });
  });

  test("지워지는 것을 보이고, 확인하면 탈퇴한 뒤 로그인 버튼으로 돌아간다", async () => {
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "회원 탈퇴" }),
    );
    expect(screen.getByText(/분석한 문장 기록/)).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/auth/withdraw/")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "탈퇴하기" }));

    expect(
      await screen.findByRole("heading", { name: "Dragram에 로그인" }),
    ).toBeInTheDocument();
    const withdraw = calls.find((c) => c.url === "/api/auth/withdraw/")!;
    expect(withdraw.method).toBe("POST");
    expect(withdraw.headers["X-CSRFToken"]).toBe("csrf-value");
    // 확인 화면에 보인 계정을 보내, 그사이 다른 계정으로 로그인했으면 서버가 거부하게 한다.
    expect(JSON.parse(withdraw.body!)).toEqual({ account: "42" });
  });

  test("취소하면 탈퇴 요청 없이 로그인한 화면으로 돌아간다", async () => {
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "회원 탈퇴" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "취소" }));

    expect(
      screen.getByRole("heading", { name: "로그인했어요" }),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/auth/withdraw/")).toBe(false);
  });

  test("그사이 다른 계정으로 로그인했으면 새로 고치라고 안내한다", async () => {
    responses["POST /api/auth/withdraw/"] = () =>
      json({ error: "AUTH:ACCOUNT_MISMATCH" }, 409);
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "회원 탈퇴" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "탈퇴하기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "다른 계정으로 로그인되어 있어요",
    );
  });

  test("탈퇴가 실패하면 확인 화면에 남아 안내한다", async () => {
    responses["POST /api/auth/withdraw/"] = () =>
      json({ error: "AUTH:CSRF_FAILED" }, 403);
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "회원 탈퇴" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "탈퇴하기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "탈퇴하지 못했어요",
    );
    expect(screen.getByRole("button", { name: "탈퇴하기" })).toBeEnabled();
  });
});

test("로그인이 거부되면 다시 시도하라고 안내한다", async () => {
  responses["POST /api/auth/google/"] = () =>
    json({ error: "AUTH:EMAIL_NOT_VERIFIED" }, 403);
  render(<ConnectPage />);
  await screen.findByRole("heading", { name: "Dragram에 로그인" });

  await act(async () => googleCallback!({ credential: "google-id-token" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "로그인하지 못했어요",
  );
});

test("Google 버튼을 준비하지 못하면 로그인 실패와 다르게 안내한다", async () => {
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "");
  render(<ConnectPage />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "로그인 버튼을 불러오지 못했어요",
  );
  expect(renderButton).not.toHaveBeenCalled();
});

test("로그아웃이 실패하면 로그인한 상태를 그대로 보이고 안내한다", async () => {
  responses["GET /api/auth/me/"] = () =>
    json({ user: { email: "me@example.com" } });
  responses["POST /api/auth/logout/"] = () =>
    json({ error: "AUTH:CSRF_FAILED" }, 403);
  render(<ConnectPage />);
  await screen.findByText("me@example.com");

  await userEvent.click(screen.getByRole("button", { name: "로그아웃" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "로그아웃하지 못했어요",
  );
  expect(screen.getByText("me@example.com")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "로그아웃" })).toBeInTheDocument();
});

describe("확장 연결(#109)", () => {
  type Message = { type: string; token?: string; account?: string };
  let sent: { extensionId: string; message: Message }[];
  let reply: { ok: boolean } | undefined;
  let lastError: { message: string } | undefined;

  beforeEach(() => {
    sent = [];
    reply = { ok: true };
    lastError = undefined;
    responses["GET /api/auth/me/"] = () =>
      json({ user: { email: "me@example.com", account: "42" } });
    responses["POST /api/auth/extension-tokens/"] = () =>
      json({ token: "extension-token", account: "42" }, 201);
    vi.stubEnv("VITE_EXTENSION_ID", "dragram-extension-id");
    const runtime = {
      get lastError() {
        return lastError;
      },
      sendMessage: (
        extensionId: string,
        message: Message,
        callback: (response?: { ok: boolean }) => void,
      ) => {
        sent.push({ extensionId, message });
        callback(reply);
      },
    };
    vi.stubGlobal("chrome", { runtime });
  });

  test("확장 연결을 누르면 토큰을 받아 확장에 넘기고 연결 성공 카드를 보인다", async () => {
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );

    expect(
      await screen.findByRole("heading", { name: "연결했어요" }),
    ).toBeInTheDocument();
    const issue = calls.find((c) => c.url === "/api/auth/extension-tokens/")!;
    expect(issue.method).toBe("POST");
    expect(issue.headers["X-CSRFToken"]).toBe("csrf-value");
    expect(sent).toEqual([
      {
        extensionId: "dragram-extension-id",
        message: {
          type: "connect",
          token: "extension-token",
          account: "42",
        },
      },
    ]);
  });

  test("그사이 다른 탭에서 다른 계정으로 로그인했으면 확장에 넘기지 않고 새로 고치라고 안내한다", async () => {
    responses["POST /api/auth/extension-tokens/"] = () =>
      json({ token: "other-token", account: "99" }, 201);
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "다른 계정으로 로그인되어 있어요",
    );
    expect(sent).toEqual([]);
    expect(
      screen.queryByRole("heading", { name: "연결했어요" }),
    ).not.toBeInTheDocument();
  });

  test("확장이 응답하지 않으면 설치를 확인하라고 안내한다", async () => {
    reply = undefined;
    lastError = { message: "Could not establish connection." };
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "확장 프로그램을 찾지 못했어요",
    );
    expect(
      screen.queryByRole("heading", { name: "연결했어요" }),
    ).not.toBeInTheDocument();
  });

  test("브라우저에 확장 연결 기능이 없어도 같은 안내를 보인다", async () => {
    vi.stubGlobal("chrome", undefined);
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "확장 프로그램을 찾지 못했어요",
    );
  });

  test("웹에서 로그아웃하면 확장에도 연결을 끊으라고 알린다", async () => {
    responses["POST /api/auth/logout/"] = () => json({ user: null });
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "로그아웃" }),
    );

    await screen.findByRole("heading", { name: "Dragram에 로그인" });
    expect(sent).toEqual([
      { extensionId: "dragram-extension-id", message: { type: "disconnect" } },
    ]);
  });

  test("탈퇴하면 확장에도 연결을 끊으라고 알린다", async () => {
    responses["POST /api/auth/withdraw/"] = () => json({ user: null });
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "회원 탈퇴" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "탈퇴하기" }));

    await screen.findByRole("heading", { name: "Dragram에 로그인" });
    expect(sent).toEqual([
      { extensionId: "dragram-extension-id", message: { type: "disconnect" } },
    ]);
  });

  test("연결하는 동안에는 로그아웃할 수 없어, 폐기된 토큰을 확장에 넘기지 않는다", async () => {
    let finishIssue!: () => void;
    responses["POST /api/auth/extension-tokens/"] = () =>
      json({ token: "extension-token", account: "42" }, 201);
    const issued = new Promise<void>((resolve) => (finishIssue = resolve));
    const original = globalThis.fetch;
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url === "/api/auth/extension-tokens/") await issued;
      return original(url, init);
    });
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );

    expect(screen.getByRole("button", { name: "로그아웃" })).toBeDisabled();
    finishIssue();
    expect(
      await screen.findByRole("heading", { name: "연결했어요" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "로그아웃" })).toBeEnabled();
  });

  test("여러 탭의 연결과 로그아웃은 탭 공용 잠금으로 한 번에 하나씩 한다", async () => {
    const locked: string[] = [];
    vi.stubGlobal("navigator", {
      ...navigator,
      locks: {
        request: (name: string, task: () => Promise<unknown>) => {
          locked.push(name);
          return task();
        },
      },
    });
    responses["POST /api/auth/logout/"] = () => json({ user: null });
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );
    await screen.findByRole("heading", { name: "연결했어요" });
    await userEvent.click(screen.getByRole("button", { name: "로그아웃" }));
    await screen.findByRole("heading", { name: "Dragram에 로그인" });

    expect(locked).toEqual(["dragram-connect", "dragram-connect"]);
  });
});

test("로그인하면 내 기록으로 가는 링크를 보인다", async () => {
  responses["GET /api/auth/me/"] = () =>
    json({ user: { email: "me@example.com", account: "42" } });
  render(<ConnectPage />);

  expect(await screen.findByRole("link", { name: "내 기록" })).toHaveAttribute(
    "href",
    "/sentences",
  );
});
