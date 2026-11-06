import { describe, expect, test, vi } from "vitest";
import { fetchMyItems, saveMyItem } from "@/utils/my-items";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import App from "./App";
import { WEB_ORIGIN, handleExternalMessage } from "@/utils/external-messages";
import { fetchNames } from "@/utils/names";
import { signOut } from "@/utils/auth";
import {
  approvedGrammarItem,
  cardOf,
  grammarItem,
  ndjson,
  panelWindowId,
  respondWith,
  send,
  withParts,
  wordItem,
} from "./app-test-support";

// 지정한 이름 API(#136)는 분석 요청의 fetch 가짜와 섞이지 않게 따로 가짜로 둔다.
vi.mock("@/utils/my-items", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/my-items")>()),
  fetchMyItems: vi.fn(),
  saveMyItem: vi.fn(),
}));

vi.mock("@/utils/names", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/names")>()),
  fetchNames: vi.fn(),
  saveName: vi.fn(),
  removeName: vi.fn(),
}));

describe("내 일본어 항목(#321)", () => {
  const SENTENCE = "私は学生です";

  function respondWithCards() {
    respondWith(200, {
      translation_ko: "나는 학생입니다.",
      grammar: [
        { ...grammarItem(1, 2, "주제 は", "は"), usage_id: 11 },
        { ...grammarItem(4, 6, "정중 です", "です"), usage_id: 12 },
      ],
      words: [wordItem(2, 4, "学生", "がくせい", { id: 21 })],
    });
  }

  const highlights = () => document.querySelectorAll("mark.highlight").length;

  test("카드에서 추가하면 '추가됨'과 예문 저장 버튼을 보이고, 예문은 누를 때만 이 문장으로 보낸다", async () => {
    respondWithCards();
    vi.mocked(saveMyItem).mockResolvedValue({
      kind: "usage",
      id: 11,
      added: true,
      hidden: false,
    });
    render(<App />);
    await send(panelWindowId, SENTENCE);
    await screen.findByRole("heading", { name: "주제 は" });

    fireEvent.click(
      within(cardOf("주제 は")).getByRole("button", { name: "추가" }),
    );

    expect(
      await within(cardOf("주제 は")).findByRole("button", { name: "추가됨" }),
    ).toBeInTheDocument();
    expect(saveMyItem).toHaveBeenCalledWith(
      "usage",
      11,
      { added: true },
      undefined,
    );
    fireEvent.click(
      within(cardOf("주제 は")).getByRole("button", {
        name: "예문 저장",
      }),
    );
    expect(
      await within(cardOf("주제 は")).findByText("예문 저장됨"),
    ).toBeInTheDocument();
    // 예문과 함께 이 카드가 가리키는 부분(は)의 위치도 보낸다.
    expect(saveMyItem).toHaveBeenLastCalledWith(
      "usage",
      11,
      { added: true },
      {
        text: SENTENCE,
        start: 1,
        end: 2,
      },
    );
    // 다른 카드는 그대로다.
    expect(
      within(cardOf("정중 です")).getByRole("button", { name: "추가" }),
    ).toBeInTheDocument();
  });

  test("'선택한 카드'에서도 추가할 수 있고, '숨김'을 누르면 형광펜과 함께 박스가 닫힌다", async () => {
    respondWithCards();
    vi.mocked(saveMyItem)
      .mockResolvedValueOnce({
        kind: "usage",
        id: 11,
        added: true,
        hidden: false,
      })
      .mockResolvedValueOnce({
        kind: "usage",
        id: 12,
        added: false,
        hidden: true,
      });
    render(<App />);
    await send(panelWindowId, SENTENCE);
    await screen.findByRole("heading", { name: "주제 は" });
    fireEvent.click(screen.getByRole("button", { name: "は" }));
    const box = () => screen.getByRole("region", { name: "선택한 카드" });

    fireEvent.click(within(box()).getByRole("button", { name: "추가" }));

    expect(
      await within(box()).findByRole("button", { name: "추가됨" }),
    ).toBeInTheDocument();
    expect(saveMyItem).toHaveBeenCalledWith(
      "usage",
      11,
      { added: true },
      undefined,
    );

    fireEvent.click(screen.getByRole("button", { name: "です" }));
    fireEvent.click(within(box()).getByRole("button", { name: "숨김" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("region", { name: "선택한 카드" }),
      ).not.toBeInTheDocument(),
    );
    expect(saveMyItem).toHaveBeenLastCalledWith(
      "usage",
      12,
      { hidden: true },
      undefined,
    );
    expect(highlights()).toBe(1);

    // 단어 카드도 목록과 같은 추가 버튼을 단다.
    fireEvent.click(screen.getByRole("button", { name: "学生" }));
    expect(
      within(box()).getByRole("heading", { name: "学生" }),
    ).toBeInTheDocument();
    expect(
      within(box()).getByRole("button", { name: "추가" }),
    ).toBeInTheDocument();
  });

  test("'숨김'은 카드·형광펜·개수에서 빼고 맨 아래에 접어 두며, '복원'으로 돌아온다", async () => {
    respondWithCards();
    vi.mocked(saveMyItem)
      .mockResolvedValueOnce({
        kind: "usage",
        id: 11,
        added: false,
        hidden: true,
      })
      .mockResolvedValueOnce({
        kind: "usage",
        id: 11,
        added: false,
        hidden: false,
      });
    render(<App />);
    await send(panelWindowId, SENTENCE);
    await screen.findByRole("heading", { name: "주제 は" });
    expect(highlights()).toBe(2);

    fireEvent.click(
      within(cardOf("주제 は")).getByRole("button", { name: "숨김" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "주제 は" }),
      ).not.toBeInTheDocument(),
    );
    expect(saveMyItem).toHaveBeenCalledWith(
      "usage",
      11,
      { hidden: true },
      undefined,
    );
    expect(highlights()).toBe(1);
    expect(screen.getByRole("tab", { name: "문법 1" })).toBeInTheDocument();
    const hidden = within(screen.getByRole("list", { name: "숨긴 카드" }));
    expect(screen.getByText("숨긴 카드 1개")).toBeInTheDocument();
    expect(hidden.getByText("주제 は")).toBeInTheDocument();
    // 미검수 용법은 숨긴 줄에서도 배지를 단다.
    expect(hidden.getByText("AI 생성·미검수")).toBeInTheDocument();

    fireEvent.click(hidden.getByRole("button", { name: "복원" }));

    expect(
      await screen.findByRole("heading", { name: "주제 は" }),
    ).toBeInTheDocument();
    expect(saveMyItem).toHaveBeenLastCalledWith(
      "usage",
      11,
      { hidden: false },
      undefined,
    );
    expect(highlights()).toBe(2);
    expect(
      within(cardOf("주제 は")).getByRole("button", { name: "추가" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/숨긴 카드/)).not.toBeInTheDocument();
  });

  test("이미 숨긴 단어는 처음부터 단어 탭에서 빠져 접혀 있다", async () => {
    respondWithCards();
    vi.mocked(fetchMyItems).mockResolvedValue([
      { kind: "sense", id: 21, added: false, hidden: true },
    ]);
    render(<App />);
    await send(panelWindowId, SENTENCE);

    fireEvent.click(await screen.findByRole("tab", { name: "단어 0" }));

    expect(screen.queryByRole("heading", { name: "学生" })).toBeNull();
    expect(screen.getByText("숨긴 카드 1개")).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "숨긴 카드" })).getByText(
        "学生 뜻",
      ),
    ).toBeInTheDocument();
  });

  test("추가한 카드에서 '숨김'을 누르면 예문은 그대로 두고 숨긴 카드로 보낸다", async () => {
    respondWithCards();
    vi.mocked(fetchMyItems).mockResolvedValue([
      { kind: "usage", id: 12, added: true, hidden: false, has_examples: true },
    ]);
    vi.mocked(saveMyItem).mockResolvedValue({
      kind: "usage",
      id: 12,
      added: true,
      hidden: true,
    });
    render(<App />);
    await send(panelWindowId, SENTENCE);
    const card = () => cardOf("정중 です");
    expect(
      await within(await waitFor(card)).findByRole("button", {
        name: "추가됨",
      }),
    ).toBeInTheDocument();
    expect(
      within(card()).queryByRole("button", { name: "빼기" }),
    ).not.toBeInTheDocument();

    // 숨김은 예문을 지우지 않아 확인받지 않는다.
    fireEvent.click(within(card()).getByRole("button", { name: "숨김" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "정중 です" }),
      ).not.toBeInTheDocument(),
    );
    expect(saveMyItem).toHaveBeenCalledWith(
      "usage",
      12,
      { hidden: true },
      undefined,
    );
    expect(
      within(screen.getByRole("list", { name: "숨긴 카드" })).getByText(
        "정중 です",
      ),
    ).toBeInTheDocument();
  });

  test("추가했다가 숨긴 카드는 숨긴 줄에 '추가됨'을 달고, 복원하면 확인 없이 예문과 함께 추가됨으로 돌아온다", async () => {
    respondWithCards();
    vi.mocked(fetchMyItems).mockResolvedValue([
      { kind: "usage", id: 11, added: true, hidden: true, has_examples: true },
      { kind: "usage", id: 12, added: false, hidden: true },
    ]);
    vi.mocked(saveMyItem).mockResolvedValue({
      kind: "usage",
      id: 11,
      added: true,
      hidden: false,
    });
    render(<App />);
    await send(panelWindowId, SENTENCE);
    const hidden = within(
      await screen.findByRole("list", { name: "숨긴 카드" }),
    );
    const [addedRow, plainRow] = hidden.getAllByRole("listitem");
    expect(within(addedRow!).getByText("추가됨")).toBeInTheDocument();
    expect(within(plainRow!).queryByText("추가됨")).toBeNull();

    fireEvent.click(within(addedRow!).getByRole("button", { name: "복원" }));

    expect(
      await within(await waitFor(() => cardOf("주제 は"))).findByRole(
        "button",
        { name: "추가됨" },
      ),
    ).toHaveAttribute("aria-pressed", "true");
    expect(saveMyItem).toHaveBeenCalledWith(
      "usage",
      11,
      { hidden: false },
      undefined,
    );
    expect(
      screen.queryByText("저장한 예문도 함께 지워져요. 되돌릴 수 없어요."),
    ).toBeNull();
  });

  test("'추가됨'은 다시 누르면 제외하는 토글이고, 예문이 있으면 지워짐을 한 번 확인받는다", async () => {
    respondWithCards();
    vi.mocked(fetchMyItems).mockResolvedValue([
      { kind: "usage", id: 11, added: true, hidden: false },
      { kind: "usage", id: 12, added: true, hidden: false, has_examples: true },
    ]);
    vi.mocked(saveMyItem)
      .mockResolvedValueOnce({
        kind: "usage",
        id: 11,
        added: false,
        hidden: false,
      })
      .mockResolvedValueOnce({
        kind: "usage",
        id: 12,
        added: false,
        hidden: false,
      });
    render(<App />);
    await send(panelWindowId, SENTENCE);
    const toggle = async (name: string) =>
      within(await waitFor(() => cardOf(name))).findByRole("button", {
        name: "추가됨",
      });
    expect(await toggle("주제 は")).toHaveAttribute("aria-pressed", "true");
    // 누르면 제외된다는 것을 미리 알린다.
    expect(await toggle("주제 は")).toHaveAttribute(
      "title",
      "다시 누르면 내 일본어에서 제외해요",
    );

    // 예문이 없으면 바로 제외한다.
    fireEvent.click(await toggle("주제 は"));
    expect(
      await within(cardOf("주제 は")).findByRole("button", { name: "추가" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(saveMyItem).toHaveBeenCalledWith(
      "usage",
      11,
      { added: false },
      undefined,
    );

    fireEvent.click(await toggle("정중 です"));
    expect(saveMyItem).toHaveBeenCalledTimes(1);
    fireEvent.click(
      within(cardOf("정중 です")).getByRole("button", { name: "취소" }),
    );
    fireEvent.click(await toggle("정중 です"));
    fireEvent.click(
      within(cardOf("정중 です")).getByRole("button", {
        name: "예문과 함께 제외",
      }),
    );
    await waitFor(() =>
      expect(saveMyItem).toHaveBeenLastCalledWith(
        "usage",
        12,
        { added: false },
        undefined,
      ),
    );
  });

  test("복원에 실패하면 숨긴 채로 두고 알린다", async () => {
    respondWithCards();
    vi.mocked(fetchMyItems).mockResolvedValue([
      { kind: "usage", id: 11, added: false, hidden: true },
    ]);
    vi.mocked(saveMyItem).mockRejectedValue(new Error("실패"));
    render(<App />);
    await send(panelWindowId, SENTENCE);
    const hidden = within(
      await screen.findByRole("list", { name: "숨긴 카드" }),
    );

    fireEvent.click(hidden.getByRole("button", { name: "복원" }));

    expect(
      await screen.findByText("바꾸지 못했습니다. 다시 시도해 주세요."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "주제 は" })).toBeNull();
  });

  test("웹에서 항목을 바꿨다고 알리면 패널을 다시 열지 않아도 항목을 다시 불러온다", async () => {
    respondWithCards();
    vi.mocked(fetchMyItems).mockResolvedValue([]);
    render(<App />);
    await send(panelWindowId, SENTENCE);
    await screen.findByRole("heading", { name: "주제 は" });
    vi.mocked(fetchMyItems).mockResolvedValue([
      { kind: "usage", id: 11, added: false, hidden: true },
    ]);

    await handleExternalMessage(
      { type: "items-changed" },
      `${WEB_ORIGIN}/sentences`,
    );

    expect(await screen.findByText("숨긴 카드 1개")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "주제 は" })).toBeNull();
  });

  test("구성 문법 하위 박스에서도 추가하고 예문을 저장한다", async () => {
    respondWith(200, {
      translation_ko: "나는 학생입니다.",
      grammar: [
        withParts(
          { ...grammarItem(2, 6, "바깥 문법", "学生です"), usage_id: 30 },
          { ...grammarItem(4, 6, "정중 です", "です"), usage_id: 12 },
        ),
      ],
      words: [],
    });
    vi.mocked(fetchMyItems).mockResolvedValue([]);
    vi.mocked(saveMyItem).mockResolvedValue({
      kind: "usage",
      id: 12,
      added: true,
      hidden: false,
    });
    render(<App />);
    await send(panelWindowId, SENTENCE);

    const part = within(
      await screen.findByRole("list", { name: "구성 문법" }),
    ).getByRole("listitem");
    fireEvent.click(within(part).getByRole("button", { name: "추가" }));
    expect(
      await within(part).findByRole("button", { name: "추가됨" }),
    ).toBeInTheDocument();
    fireEvent.click(within(part).getByRole("button", { name: "예문 저장" }));

    await within(part).findByText("예문 저장됨");
    // 예문에는 하위 박스(です)의 자리를 보낸다.
    expect(saveMyItem).toHaveBeenLastCalledWith(
      "usage",
      12,
      { added: true },
      {
        text: SENTENCE,
        start: 4,
        end: 6,
      },
    );
  });

  test("하위 박스에서 숨기면 바깥 카드는 두고 그 하위 박스만 빠져 숨긴 카드에 모이고, 복원하면 돌아온다", async () => {
    respondWith(200, {
      translation_ko: "나는 학생입니다.",
      grammar: [
        withParts(
          { ...grammarItem(2, 6, "바깥 문법", "学生です"), usage_id: 30 },
          { ...grammarItem(4, 6, "정중 です", "です"), usage_id: 12 },
        ),
      ],
      words: [],
    });
    vi.mocked(fetchMyItems).mockResolvedValue([]);
    vi.mocked(saveMyItem)
      .mockResolvedValueOnce({
        kind: "usage",
        id: 12,
        added: false,
        hidden: true,
      })
      .mockResolvedValueOnce({
        kind: "usage",
        id: 12,
        added: false,
        hidden: false,
      });
    render(<App />);
    await send(panelWindowId, SENTENCE);
    expect(
      await screen.findByRole("tab", { name: "문법 2" }),
    ).toBeInTheDocument();
    const part = within(
      screen.getByRole("list", { name: "구성 문법" }),
    ).getByRole("listitem");

    fireEvent.click(within(part).getByRole("button", { name: "숨김" }));

    expect(
      await screen.findByRole("tab", { name: "문법 1" }),
    ).toBeInTheDocument();
    expect(saveMyItem).toHaveBeenCalledWith(
      "usage",
      12,
      { hidden: true },
      undefined,
    );
    expect(
      screen.getByRole("heading", { name: "바깥 문법" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "구성 문법" })).toBeNull();
    const hidden = within(screen.getByRole("list", { name: "숨긴 카드" }));
    fireEvent.click(hidden.getByRole("button", { name: "복원" }));

    expect(
      await screen.findByRole("tab", { name: "문법 2" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "구성 문법" })).toBeInTheDocument();
  });

  test("숨긴 용법은 다른 카드의 구성 문법에서도 빠지고 숨긴 카드에 모인다", async () => {
    respondWith(200, {
      translation_ko: "나는 학생입니다.",
      grammar: [
        withParts(
          { ...grammarItem(2, 6, "바깥 문법", "学生です"), usage_id: 30 },
          { ...grammarItem(4, 6, "정중 です", "です"), usage_id: 12 },
        ),
      ],
      words: [],
    });
    vi.mocked(fetchMyItems).mockResolvedValue([
      { kind: "usage", id: 12, added: false, hidden: true },
    ]);
    render(<App />);
    await send(panelWindowId, SENTENCE);

    await screen.findByRole("heading", { name: "바깥 문법" });
    await waitFor(() =>
      expect(
        screen.queryByRole("list", { name: "구성 문법" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("tab", { name: "문법 1" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "숨긴 카드" })).getByText(
        "정중 です",
      ),
    ).toBeInTheDocument();
  });

  test("바깥 문법을 숨기면 그 안의 구성 문법도 함께 숨는다", async () => {
    respondWith(200, {
      translation_ko: "나는 학생입니다.",
      grammar: [
        withParts(
          { ...grammarItem(2, 6, "바깥 문법", "学生です"), usage_id: 30 },
          { ...grammarItem(4, 6, "정중 です", "です"), usage_id: 12 },
        ),
      ],
      words: [],
    });
    vi.mocked(fetchMyItems).mockResolvedValue([
      { kind: "usage", id: 30, added: false, hidden: true },
    ]);
    render(<App />);
    await send(panelWindowId, SENTENCE);

    // 다시 분석해도 구성 문법이 독립 카드로 튀어나오지 않는다. 숨긴 카드에는 바깥만 모인다.
    expect(await screen.findByText("숨긴 카드 1개")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "바깥 문법" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "정중 です" })).toBeNull();
  });

  test("지정한 이름 행은 그 사전 뜻을 숨겨도 남는다", async () => {
    respondWithCards();
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "学生", reading: "がくせい" },
    ]);
    vi.mocked(fetchMyItems).mockResolvedValue([
      { kind: "sense", id: 21, added: false, hidden: true },
    ]);
    render(<App />);
    await send(panelWindowId, SENTENCE);

    fireEvent.click(await screen.findByRole("tab", { name: /^단어/ }));

    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(screen.queryByText(/숨긴 카드/)).not.toBeInTheDocument();
  });

  test("분석이 실패해 탭 없이 남은 문법에서도 숨긴 카드를 되돌릴 수 있다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        ndjson([
          {
            type: "grammar",
            grammar: [{ ...approvedGrammarItem(3, 6, "진행"), usage_id: 11 }],
          },
          { type: "error", error: "ANALYSIS:FAILED" },
        ]),
      ),
    );
    vi.mocked(saveMyItem).mockResolvedValue({
      kind: "usage",
      id: 11,
      added: false,
      hidden: true,
    });
    render(<App />);
    await send(panelWindowId, "彼が来ている");
    expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();

    fireEvent.click(
      within(cardOf("진행")).getByRole("button", { name: "숨김" }),
    );

    expect(await screen.findByText("숨긴 카드 1개")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "진행" })).toBeNull();
  });

  test("같은 뜻이 두 줄에 있어도 바꾸기 요청은 앞 요청이 끝난 뒤 보낸다", async () => {
    respondWith(200, {
      translation_ko: "나는 학생입니다.",
      grammar: [],
      words: [
        wordItem(0, 1, "私", "わたし", { id: 21 }),
        wordItem(2, 4, "学生", "がくせい", { id: 21 }),
      ],
    });
    let finishAdd!: () => void;
    vi.mocked(saveMyItem)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishAdd = () =>
              resolve({ kind: "sense", id: 21, added: true, hidden: false });
          }),
      )
      .mockResolvedValueOnce({
        kind: "sense",
        id: 21,
        added: false,
        hidden: true,
      });
    render(<App />);
    await send(panelWindowId, SENTENCE);
    fireEvent.click(await screen.findByRole("tab", { name: /^단어/ }));
    const [first, second] = screen
      .getAllByRole("listitem")
      .filter((li) => li.classList.contains("word-row"));

    fireEvent.click(within(first!).getByRole("button", { name: "추가" }));
    fireEvent.click(within(second!).getByRole("button", { name: "숨김" }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(saveMyItem).toHaveBeenCalledTimes(1);
    finishAdd();

    expect(await screen.findByText("숨긴 카드 1개")).toBeInTheDocument();
    expect(saveMyItem).toHaveBeenCalledTimes(2);
    expect(saveMyItem).toHaveBeenLastCalledWith(
      "sense",
      21,
      { hidden: true },
      undefined,
    );
  });

  test("기다리던 바꾸기 요청은 그사이 로그아웃했으면 보내지 않는다", async () => {
    respondWith(200, {
      translation_ko: "나는 학생입니다.",
      grammar: [],
      words: [
        wordItem(0, 1, "私", "わたし", { id: 21 }),
        wordItem(2, 4, "学生", "がくせい", { id: 21 }),
      ],
    });
    let finishAdd!: () => void;
    vi.mocked(saveMyItem).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishAdd = () =>
            resolve({ kind: "sense", id: 21, added: true, hidden: false });
        }),
    );
    render(<App />);
    await send(panelWindowId, SENTENCE);
    fireEvent.click(await screen.findByRole("tab", { name: /^단어/ }));
    const [first, second] = screen
      .getAllByRole("listitem")
      .filter((li) => li.classList.contains("word-row"));
    fireEvent.click(within(first!).getByRole("button", { name: "추가" }));
    fireEvent.click(within(second!).getByRole("button", { name: "숨김" }));

    await signOut();
    await waitFor(() =>
      expect(screen.queryByRole("tab", { name: /^단어/ })).toBeNull(),
    );
    finishAdd();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(saveMyItem).toHaveBeenCalledTimes(1);
  });

  test("저장에 실패하면 상태를 바꾸지 않고 알린다", async () => {
    respondWithCards();
    vi.mocked(saveMyItem).mockRejectedValue(new Error("실패"));
    render(<App />);
    await send(panelWindowId, SENTENCE);
    await screen.findByRole("heading", { name: "주제 は" });

    fireEvent.click(
      within(cardOf("주제 は")).getByRole("button", { name: "숨김" }),
    );

    expect(
      await screen.findByText("저장하지 못했습니다. 다시 시도해 주세요."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "주제 は" }),
    ).toBeInTheDocument();
    expect(
      within(cardOf("주제 は")).getByRole("button", { name: "추가" }),
    ).toBeInTheDocument();
  });
});
