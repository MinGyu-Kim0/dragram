import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
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
  expect(renderButton).toHaveBeenCalledTimes(1);
  expect(
    screen.queryByRole("button", { name: "로그아웃" }),
  ).not.toBeInTheDocument();
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
