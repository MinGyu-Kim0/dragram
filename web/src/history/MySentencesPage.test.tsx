import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { sendToExtension } from "../connect/extension";
import { json, stubFetch } from "../test-support";
import MySentencesPage from "./MySentencesPage";

vi.mock("../connect/extension", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../connect/extension")>()),
  sendToExtension: vi.fn(async () => true),
}));

type Call = { url: string; method: string; body?: unknown };

let calls: Call[];
let responses: Record<string, () => Response>;

const USAGES = [
  {
    usage_id: 7,
    pattern_name: "ている",
    name: "진행",
    explanation_ko: "동작이 이어지고 있음을 나타낸다",
    korean_equivalent: "~하고 있다",
    korean_equivalent_review_status: "approved",
    review_status: "pending",
    examples: [{ id: 31, text: "雨が降っている。", start: 4, end: 7 }],
  },
  {
    usage_id: 3,
    pattern_name: "です",
    name: "정중",
    explanation_ko: "정중하게 단정한다",
    korean_equivalent: null,
    korean_equivalent_review_status: null,
    review_status: "approved",
    examples: [],
  },
];

const WORDS = [
  {
    sense_id: 11,
    dictionary_form: "走る",
    reading: "はしる",
    tags: ["verb", "group1"],
    in_dictionary: true,
    sense: {
      id: 11,
      tags: [],
      gloss_en: ["to run"],
      origin: "jmdict",
      status: "approved",
      meaning_ko: "달리다",
      meaning_status: "ai",
    },
    examples: [],
  },
  {
    sense_id: 12,
    rejected: true,
    examples: [{ id: 41, text: "春が来た。", start: null, end: null }],
  },
];

beforeEach(() => {
  calls = [];
  document.cookie = "csrftoken=csrf-value";
  responses = {
    "GET /api/auth/me/": () =>
      json({ user: { email: "me@example.com", account: "42" } }),
    "GET /api/my-japanese/grammar/?state=added": () => json({ usages: USAGES }),
    "GET /api/my-japanese/words/?state=added": () => json({ words: WORDS }),
  };
  stubFetch(responses, (url, method, init) =>
    calls.push({
      url,
      method,
      body: init.body ? JSON.parse(init.body as string) : undefined,
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function open(path = "/sentences") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/sentences" element={<MySentencesPage />} />
        <Route path="/connect" element={<p>로그인 화면</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

// 카드 안의 예문 목록 항목은 빼고 카드만 고른다.
async function cards(name: string) {
  const list = await screen.findByRole("list", { name });
  return within(list)
    .getAllByRole("listitem")
    .filter((li) => li.parentElement === list);
}

test("문법 탭이 기본이고 추가한 용법을 미검수 배지·대응 표현·예문과 함께 보인다", async () => {
  open();

  expect(
    await screen.findByRole("tab", { name: "문법", selected: true }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "추가한 항목", pressed: true }),
  ).toBeInTheDocument();
  const [first, second] = await cards("추가한 문법");
  expect(first).toHaveTextContent("ている");
  expect(first).toHaveTextContent("~하고 있다");
  expect(within(first).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(within(second).queryByText("AI 생성·미검수")).toBeNull();
  const example = within(
    within(first).getByRole("list", { name: "내 예문" }),
  ).getByRole("listitem");
  expect(example).toHaveTextContent("雨が降っている。");
  // 예문을 저장한 카드가 가리키던 부분을 사이드 패널처럼 표시한다.
  expect(example.querySelector("mark")).toHaveTextContent(/^ている$/);
  expect(screen.queryByRole("tab", { name: "문장" })).toBeNull();
});

test("문법 카드의 대응 표현 앞에 '뜻', 설명 앞에 '설명' 라벨을 단다", async () => {
  open();

  const [first, second] = await cards("추가한 문법");
  expect(
    within(within(first).getByText("~하고 있다")).getByText("뜻"),
  ).toBeVisible();
  expect(
    within(
      within(first).getByText("동작이 이어지고 있음을 나타낸다"),
    ).getByText("설명"),
  ).toBeVisible();
  // 대응 표현이 없으면 '뜻' 라벨도 없다.
  expect(within(second).queryByText("뜻")).toBeNull();
  expect(
    within(within(second).getByText("정중하게 단정한다")).getByText("설명"),
  ).toBeVisible();
});

test("숨김을 누르면 서버에 보내고 목록에서 뺀다", async () => {
  responses["PUT /api/my-items/"] = () =>
    json({ kind: "usage", id: 3, added: true, hidden: true });
  open();
  const [, second] = await cards("추가한 문법");

  await userEvent.click(within(second).getByRole("button", { name: "숨김" }));

  expect(calls.at(-1)).toEqual({
    url: "/api/my-items/",
    method: "PUT",
    body: { kind: "usage", id: 3, hidden: true },
  });
  expect(screen.queryByText("정중")).toBeNull();
  // 열린 사이드 패널이 바로 다시 불러오게 확장에 알린다.
  expect(sendToExtension).toHaveBeenCalledWith({ type: "items-changed" });
});

test("사이드 패널에서 바꾸고 이 창으로 돌아오면 목록을 다시 불러온다", async () => {
  open();
  await cards("추가한 문법");
  responses["GET /api/my-japanese/grammar/?state=added"] = () =>
    json({ usages: [USAGES[1]] });

  window.dispatchEvent(new Event("focus"));

  await waitFor(() => expect(screen.queryByText("진행")).toBeNull());
  expect(screen.getByText("정중")).toBeInTheDocument();
});

test("다시 불러오는 사이 숨긴 항목은 늦게 온 이전 응답으로 되살아나지 않는다", async () => {
  responses["PUT /api/my-items/"] = () =>
    json({ kind: "usage", id: 3, added: true, hidden: true });
  open();
  const [, second] = await cards("추가한 문법");
  let finishStale: (r: Response) => void = () => {};
  responses["GET /api/my-japanese/grammar/?state=added"] = () => {
    // 첫 재조회는 숨기기 전 목록을 늦게 돌려준다. 그 뒤로는 서버의 새 상태다.
    responses["GET /api/my-japanese/grammar/?state=added"] = () =>
      json({ usages: [USAGES[0]] });
    return new Promise<Response>((resolve) => (finishStale = resolve)) as never;
  };
  window.dispatchEvent(new Event("focus"));

  await userEvent.click(within(second).getByRole("button", { name: "숨김" }));
  finishStale(json({ usages: USAGES }));

  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(screen.queryByText("정중")).toBeNull();
  expect(screen.getByText("진행")).toBeInTheDocument();
});

test("예문이 있는 항목은 한 번 확인받고 예문과 함께 제외한다", async () => {
  responses["PUT /api/my-items/"] = () =>
    json({ kind: "usage", id: 7, added: false, hidden: false });
  open();
  const [first] = await cards("추가한 문법");

  await userEvent.click(within(first).getByRole("button", { name: "제외" }));
  expect(calls.some((c) => c.method === "PUT")).toBe(false);
  await userEvent.click(
    within(first).getByRole("button", { name: "예문과 함께 제외" }),
  );

  expect(calls.at(-1)).toEqual({
    url: "/api/my-items/",
    method: "PUT",
    body: { kind: "usage", id: 7, added: false },
  });
  expect(screen.queryByText("진행")).toBeNull();
});

test("예문을 하나씩 지울 수 있다", async () => {
  responses["DELETE /api/my-examples/31/"] = () =>
    new Response(null, { status: 204 });
  open();
  const [first] = await cards("추가한 문법");

  await userEvent.click(
    within(first).getByRole("button", { name: "예문 지우기" }),
  );

  expect(screen.queryByText("雨が降っている。")).toBeNull();
  expect(screen.getByText("진행")).toBeInTheDocument();
});

test("숨긴 항목 필터에서 확인 없이 복원하거나 제외한다", async () => {
  responses["GET /api/my-japanese/grammar/?state=hidden"] = () =>
    json({ usages: [USAGES[1], { ...USAGES[0], examples: [] }] });
  responses["PUT /api/my-items/"] = () =>
    json({ kind: "usage", id: 3, added: true, hidden: false });
  open();
  await cards("추가한 문법");

  await userEvent.click(screen.getByRole("button", { name: "숨긴 항목" }));
  const [restored, excluded] = await cards("숨긴 문법");
  expect(
    within(restored).queryByRole("button", { name: "추가로 바꾸기" }),
  ).toBeNull();
  await userEvent.click(within(restored).getByRole("button", { name: "복원" }));
  await userEvent.click(within(excluded).getByRole("button", { name: "제외" }));

  expect(calls.filter((c) => c.method === "PUT")).toEqual([
    {
      url: "/api/my-items/",
      method: "PUT",
      body: { kind: "usage", id: 3, hidden: false },
    },
    {
      url: "/api/my-items/",
      method: "PUT",
      body: { kind: "usage", id: 7, added: false },
    },
  ]);
  expect(await screen.findByText("숨긴 문법이 없어요.")).toBeInTheDocument();
});

test("단어 탭은 뜻·AI 번역·출처를 보이고, 검수에서 빠진 뜻은 예문과 제외만 보인다", async () => {
  open("/sentences?tab=words");

  const [run, rejected] = await cards("추가한 단어");
  expect(within(run).getByRole("heading", { name: "走る" })).toBeVisible();
  expect(run).toHaveTextContent("달리다");
  expect(within(within(run).getByText("달리다")).getByText("뜻")).toBeVisible();
  expect(within(run).getByText("AI 번역")).toBeInTheDocument();
  expect(rejected).toHaveTextContent("검수에서 빠진 단어 뜻이에요");
  expect(rejected).toHaveTextContent("春が来た。");
  // 위치가 없는 예문은 표시 없이 보인다.
  expect(rejected.querySelector("mark")).toBeNull();
  expect(within(rejected).queryByRole("button", { name: "숨김" })).toBeNull();
  expect(
    within(rejected).getByRole("button", { name: "제외" }),
  ).toBeInTheDocument();
  const panel = within(screen.getByRole("tabpanel"));
  expect(panel.getByRole("link", { name: "CC BY-SA 4.0" })).toBeVisible();
});

test("'보통 가나로 씀' 뜻은 읽기를 표제로, 한자 사전형을 회색 글자로 보인다", async () => {
  const uk = (id: number, form: string, reading: string) => ({
    ...WORDS[0],
    sense_id: id,
    dictionary_form: form,
    reading,
    tags: ["noun"],
    sense: { ...WORDS[0]!.sense, id, tags: ["uk"] },
  });
  responses["GET /api/my-japanese/words/?state=added"] = () =>
    json({
      words: [
        uk(21, "沢山", "たくさん"),
        uk(22, "ある", "ある"),
        WORDS[0],
        { ...uk(23, "紙", "かみ"), sense: null },
      ],
    });
  open("/sentences?tab=words");

  const rows = await cards("추가한 단어");
  expect(
    rows.map((row) => [
      within(row).getByRole("heading").textContent,
      row.querySelector(".word-head .muted")!.textContent,
    ]),
  ).toEqual([
    ["たくさん", "沢山"],
    ["ある", "ある"],
    ["走る", "はしる"],
    ["紙", "かみ"],
  ]);
});

test("바꾸지 못하면 항목을 남기고 알린다", async () => {
  responses["PUT /api/my-items/"] = () =>
    json({ error: "AUTH:CSRF_FAILED" }, 403);
  open();
  const [, second] = await cards("추가한 문법");

  await userEvent.click(within(second).getByRole("button", { name: "숨김" }));

  expect(await within(second).findByRole("alert")).toHaveTextContent(
    "바꾸지 못했어요",
  );
  expect(screen.getByText("정중")).toBeInTheDocument();
});

test("비어 있으면 사이드 패널에서 추가하라고 안내한다", async () => {
  responses["GET /api/my-japanese/grammar/?state=added"] = () =>
    json({ usages: [] });
  open();

  expect(
    await screen.findByText(/사이드 패널의 문법 카드에서 '추가'를 눌러 보세요/),
  ).toBeInTheDocument();
});

test("로그인하지 않았으면 로그인 화면으로 간다", async () => {
  responses["GET /api/auth/me/"] = () => json({ user: null });
  open();

  expect(await screen.findByText("로그인 화면")).toBeInTheDocument();
  expect(calls.map((c) => c.url)).not.toContain(
    "/api/my-japanese/grammar/?state=added",
  );
});

test("옛 문장 분석 주소는 내 기록으로 보낸다", async () => {
  render(
    <MemoryRouter initialEntries={["/sentences/5"]}>
      <App />
    </MemoryRouter>,
  );

  expect(
    await screen.findByRole("heading", { level: 1, name: "내 기록" }),
  ).toBeInTheDocument();
});

test("예문이 있는 숨긴 항목도 복원은 예문을 지우지 않아 확인 없이 바로 한다", async () => {
  responses["GET /api/my-japanese/grammar/?state=hidden"] = () =>
    json({ usages: [USAGES[0]] });
  responses["PUT /api/my-items/"] = () =>
    json({ kind: "usage", id: 7, added: true, hidden: false });
  open("/sentences?state=hidden");
  const [card] = await cards("숨긴 문법");

  await userEvent.click(within(card).getByRole("button", { name: "복원" }));

  expect(calls.at(-1)).toEqual({
    url: "/api/my-items/",
    method: "PUT",
    body: { kind: "usage", id: 7, hidden: false },
  });
  expect(
    screen.queryByText("저장한 예문도 함께 지워져요. 되돌릴 수 없어요."),
  ).toBeNull();
});

test("예문을 지우는 동안 그 예문만 다시 누를 수 없고, 다른 예문도 함께 지울 수 있다", async () => {
  const pending: ((r: Response) => void)[] = [];
  responses["GET /api/my-japanese/grammar/?state=added"] = () =>
    json({
      usages: [
        {
          ...USAGES[0],
          examples: [
            { id: 31, text: "雨が降っている。", start: 4, end: 7 },
            { id: 32, text: "猫が寝ている。", start: 3, end: 6 },
          ],
        },
      ],
    });
  for (const id of [31, 32])
    responses[`DELETE /api/my-examples/${id}/`] = () =>
      new Promise<Response>((resolve) => pending.push(resolve)) as never;
  open();
  const [card] = await cards("추가한 문법");
  const [first, second] = within(card).getAllByRole("button", {
    name: "예문 지우기",
  });

  await userEvent.click(first!);
  await userEvent.click(second!);

  expect(first).toBeDisabled();
  expect(second).toBeDisabled();
  pending.forEach((resolve) => resolve(new Response(null, { status: 204 })));
  await waitFor(() => expect(screen.queryByText("猫が寝ている。")).toBeNull());
  expect(screen.queryByText("雨が降っている。")).toBeNull();
});
