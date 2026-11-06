import { describe, expect, test, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { fetchNames, removeName, saveName } from "@/utils/names";
import App from "./App";
import { saveToken } from "@/utils/auth";
import {
  json,
  panelWindowId,
  respondPerSentence,
  respondWith,
  rubies,
  rubyItem,
  send,
  streamed,
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

describe("이름 지정(#136)", () => {
  // 두 문장에 같은 표기 春이 나온다. 루비는 SudachiPy 읽기다.
  function respondWithSpring() {
    return respondPerSentence({
      春が来た: () =>
        json(200, {
          translation_ko: "봄이 왔다",
          grammar: [],
          words: [wordItem(0, 1, "春", "はる")],
          ruby: [rubyItem(0, 1, "はる")],
        }),
      春の雨: () =>
        json(200, {
          translation_ko: "봄비",
          grammar: [],
          words: [wordItem(0, 1, "春", "はる"), wordItem(2, 3, "雨", "あめ")],
          ruby: [rubyItem(0, 1, "はる"), rubyItem(2, 3, "あめ")],
        }),
    });
  }

  async function openWords() {
    fireEvent.click(await screen.findByRole("tab", { name: /^단어/ }));
  }

  async function designate(reading?: string) {
    fireEvent.click(screen.getByRole("button", { name: "이름으로 지정" }));
    if (reading !== undefined) {
      fireEvent.change(screen.getByRole("textbox", { name: "읽기" }), {
        target: { value: reading },
      });
    }
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
  }

  test("지정하면 열린 모든 문장 페이지의 같은 표기가 이름 행이 되고 다시 분석하지 않는다", async () => {
    const fetchMock = respondWithSpring();
    vi.mocked(saveName).mockResolvedValue({ surface: "春", reading: "はるか" });
    render(<App />);
    await send(panelWindowId, "春が来た", "春の雨");
    await openWords();

    await designate("ハルカ");

    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(saveName).toHaveBeenCalledWith("春", "ハルカ");
    expect(screen.queryByText("春 뜻")).not.toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はるか"]]);
    fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));
    await openWords();
    expect(screen.getAllByText("내가 지정한 이름")).toHaveLength(1);
    expect(screen.getByText("雨 뜻")).toBeInTheDocument();
    expect(rubies()).toEqual([
      ["春", "はるか"],
      ["雨", "あめ"],
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("읽기 입력에 SudachiPy 읽기를 채우고 사전 읽기 칩을 고를 수 있다", async () => {
    respondWithSpring();
    vi.mocked(saveName).mockResolvedValue({ surface: "春", reading: "はる" });
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    fireEvent.click(screen.getByRole("button", { name: "이름으로 지정" }));

    const input = screen.getByRole("textbox", { name: "읽기" });
    expect(input).toHaveValue("はる");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "はる" }));
    expect(input).toHaveValue("はる");
  });

  test("가나가 아닌 읽기는 그 자리에서 오류를 보이고 저장하지 않는다", async () => {
    respondWithSpring();
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    await designate("haru");

    expect(
      screen.getByText("읽기는 가나로만 입력해 주세요"),
    ).toBeInTheDocument();
    expect(saveName).not.toHaveBeenCalled();
  });

  test("저장에 실패하면 화면을 바꾸지 않고 실패 문구를 보인다", async () => {
    respondWithSpring();
    vi.mocked(saveName).mockRejectedValue(new Error("실패"));
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    await designate("はる");

    expect(
      await screen.findByText(
        "이름을 저장하지 못했습니다. 다시 시도해 주세요.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
    expect(screen.getByText("春 뜻")).toBeInTheDocument();
  });

  test("'사전 단어 보기'는 그 자리만 카드와 루비를 바꾸고 서버에 묻지 않는다", async () => {
    const fetchMock = respondWithSpring();
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();
    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "しゅん"]]);

    fireEvent.click(screen.getByRole("button", { name: "사전 단어 보기" }));

    expect(screen.getByText("春 뜻")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はる"]]);
    fireEvent.click(screen.getByRole("button", { name: "사전 단어 보기" }));
    expect(screen.getByText("내가 지정한 이름")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(saveName).not.toHaveBeenCalled();
    expect(removeName).not.toHaveBeenCalled();
  });

  function respondWithSpringNames(nameSpans: { start: number; end: number }[]) {
    return respondPerSentence({
      春が来た: () =>
        json(200, {
          translation_ko: "봄이 왔다",
          grammar: [],
          words: [wordItem(0, 1, "春", "はる")],
          ruby: [rubyItem(0, 1, "はる")],
          name_spans: nameSpans,
        }),
    });
  }

  test("이름 구간 밖의 지정한 이름은 사전 단어 행으로 시작하고 토글로 이름 행이 된다", async () => {
    respondWithSpringNames([]);
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    expect(await screen.findByText("春 뜻")).toBeInTheDocument();
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はる"]]);
    const toggle = screen.getByRole("button", { name: "사전 단어 보기" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(toggle);

    expect(screen.getByText("내가 지정한 이름")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "しゅん"]]);
    expect(
      screen.getByRole("button", { name: "사전 단어 보기" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  test("이름 구간 안의 지정한 이름은 이름 행으로 시작한다", async () => {
    respondWithSpringNames([{ start: 0, end: 1 }]);
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "しゅん"]]);

    fireEvent.click(screen.getByRole("button", { name: "사전 단어 보기" }));

    expect(screen.getByText("春 뜻")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はる"]]);
  });

  test("분석 전에 고른 보기는 이름 구간이 와도 그대로다", async () => {
    const stream = streamed();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    stream.push({
      type: "grammar",
      grammar: [],
      checking: [],
      words: [wordItem(0, 1, "春", "はる")],
    });
    await openWords();
    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "사전 단어 보기" }));

    stream.push({ type: "translation", translation_ko: "봄이 왔다", ruby: [] });
    stream.push({
      type: "analysis",
      translation_ko: "봄이 왔다",
      grammar: [],
      words: [wordItem(0, 1, "春", "はる")],
      name_spans: [],
    });
    stream.end();

    expect(await screen.findByText("봄이 왔다")).toBeInTheDocument();
    expect(screen.getByText("春 뜻")).toBeInTheDocument();
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
  });

  test("'읽기 고치기'로 읽기를 바꾼다", async () => {
    respondWithSpring();
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    vi.mocked(saveName).mockResolvedValue({ surface: "春", reading: "はる" });
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    fireEvent.click(await screen.findByRole("button", { name: "읽기 고치기" }));
    fireEvent.change(screen.getByRole("textbox", { name: "읽기" }), {
      target: { value: "はる" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(rubies()).toEqual([["春", "はる"]]));
    expect(saveName).toHaveBeenCalledWith("春", "はる");
    expect(screen.getByText("내가 지정한 이름")).toBeInTheDocument();
  });

  test("'지정 해제' 뒤 같은 표기가 단어 카드와 SudachiPy 루비로 돌아간다", async () => {
    respondWithSpring();
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    vi.mocked(removeName).mockResolvedValue();
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    fireEvent.click(await screen.findByRole("button", { name: "지정 해제" }));

    expect(await screen.findByText("春 뜻")).toBeInTheDocument();
    expect(removeName).toHaveBeenCalledWith("春");
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はる"]]);
  });

  // 패널을 연 채 다른 계정으로 연결을 바꾼다. 보던 문장은 지워지므로 같은 문장을 다시 보낸다.
  async function switchAccount() {
    await saveToken("other-token", "other@example.com");
    await waitFor(() =>
      expect(screen.queryByText("春が来た")).not.toBeInTheDocument(),
    );
    await send(panelWindowId, "春が来た");
    await openWords();
  }

  function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((r) => (resolve = r));
    return { promise, resolve };
  }

  test("계정을 바꾸면 새 계정의 목록을 받고, 이전 계정의 늦은 목록은 버린다", async () => {
    respondWithSpring();
    const old = deferred<{ surface: string; reading: string | null }[]>();
    vi.mocked(fetchNames)
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue([]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    await switchAccount();
    old.resolve([{ surface: "春", reading: "しゅん" }]);

    expect(await screen.findByText("春 뜻")).toBeInTheDocument();
    await waitFor(() => expect(fetchNames).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
  });

  test("이전 계정에서 보낸 저장의 늦은 응답은 새 계정 화면에 쓰지 않는다", async () => {
    respondWithSpring();
    const save = deferred<{ surface: string; reading: string | null }>();
    vi.mocked(saveName).mockReturnValue(save.promise);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();
    await designate("はる");

    await switchAccount();
    save.resolve({ surface: "春", reading: "はる" });

    expect(await screen.findByText("春 뜻")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
  });

  test("목록을 받는 사이 저장한 이름은 늦게 온 옛 목록에 덮이지 않는다", async () => {
    respondWithSpring();
    const first = deferred<{ surface: string; reading: string | null }[]>();
    vi.mocked(fetchNames)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue([{ surface: "春", reading: "はる" }]);
    vi.mocked(saveName).mockResolvedValue({ surface: "春", reading: "はる" });
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();
    await designate("はる");
    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();

    // 저장 전에 읽은 목록이 늦게 온다.
    first.resolve([]);

    await waitFor(() => expect(fetchNames).toHaveBeenCalledTimes(2));
    expect(screen.getByText("내가 지정한 이름")).toBeInTheDocument();
  });

  test("읽기 없이 지정한 이름은 SudachiPy 루비를 그대로 단다", async () => {
    respondWithSpring();
    vi.mocked(fetchNames).mockResolvedValue([{ surface: "春", reading: null }]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はる"]]);
  });
});

describe("이름 종류 배지(#184)", () => {
  // 東京へ行った: 東京 / 行く
  function respondWithTokyo(nameSpans: object[] | null) {
    return respondPerSentence({
      東京へ行った: () =>
        json(200, {
          translation_ko: "도쿄에 갔다",
          grammar: [],
          words: [
            wordItem(0, 2, "東京", "とうきょう"),
            wordItem(3, 5, "行く", "いく"),
          ],
          name_spans: nameSpans,
        }),
    });
  }

  async function wordRows() {
    fireEvent.click(await screen.findByRole("tab", { name: /^단어/ }));
    const list = await screen.findByRole("list", { name: "단어" });
    return within(list)
      .getAllByRole("listitem")
      .filter((row) => within(row).queryByRole("heading"));
  }

  test.each([
    ["person", "인명"],
    ["place", "지명"],
    ["org", "조직 이름"],
    ["work", "작품 이름"],
    ["other", "기타 이름"],
  ])(
    "%s 이름 구간 안의 단어 카드에만 '%s' 배지를 단다",
    async (type, label) => {
      respondWithTokyo([{ start: 0, end: 2, type }]);
      render(<App />);
      await send(panelWindowId, "東京へ行った");

      const [tokyo, iku] = await wordRows();

      expect(within(tokyo!).getByText(label)).toHaveClass("badge-neutral");
      expect(within(iku!).queryByText(label)).not.toBeInTheDocument();
      expect(screen.queryByText("AI 생성·미검수")).not.toBeInTheDocument();
    },
  );

  test("단어 카드 두 장에 걸친 이름 구간은 두 카드 모두에 배지를 단다", async () => {
    respondWithTokyo([{ start: 0, end: 5, type: "work" }]);
    render(<App />);
    await send(panelWindowId, "東京へ行った");

    const rows = await wordRows();

    for (const row of rows) {
      expect(within(row).getByText("작품 이름")).toBeInTheDocument();
    }
  });

  test.each(["니시야마", null, undefined])(
    "이름과 경칭은 별도 카드이고 접미사에는 인명 배지를 달지 않는다 (한글 읽기: %s)",
    async (readingKo) => {
      respondWith(200, {
        translation_ko: "니시야마 씨",
        grammar: [],
        name_spans: [{ start: 0, end: 4, type: "person" }],
        words: [
          {
            ...wordItem(0, 2, "西山", "にしやま", null, ["proper_noun"]),
            reading_ko: readingKo,
            is_name: true,
            in_dictionary: false,
          },
          wordItem(
            2,
            4,
            "さん",
            "さん",
            { tags: ["honorific"], meaning_ko: "씨" },
            ["suffix"],
          ),
        ],
      });
      render(<App />);
      await send(panelWindowId, "西山さん");

      const rows = await wordRows();

      expect(rows).toHaveLength(2);
      expect(screen.getByRole("tab", { name: "단어 2" })).toBeInTheDocument();
      const [person, suffix] = rows;
      expect(
        within(person!).getByRole("heading", { name: "西山" }),
      ).toBeInTheDocument();
      expect(within(person!).getByText("고유명사")).toBeInTheDocument();
      expect(within(person!).getByText("인명")).toBeInTheDocument();
      expect(within(person!).getByText("にしやま")).toBeInTheDocument();
      if (readingKo) {
        expect(within(person!).getByLabelText("한글 읽기")).toHaveTextContent(
          readingKo,
        );
      } else {
        expect(
          within(person!).queryByLabelText("한글 읽기"),
        ).not.toBeInTheDocument();
      }
      expect(
        within(person!).queryByText("AI 생성·미검수"),
      ).not.toBeInTheDocument();
      expect(within(person!).queryByRole("status")).not.toBeInTheDocument();
      expect(
        within(suffix!).getByRole("heading", { name: "さん" }),
      ).toBeInTheDocument();
      expect(within(suffix!).getByText("접미사")).toBeInTheDocument();
      expect(within(suffix!).getByText("존경어")).toBeInTheDocument();
      expect(within(suffix!).queryByText("명사")).not.toBeInTheDocument();
      expect(within(suffix!).queryByText("인명")).not.toBeInTheDocument();
      expect(
        within(suffix!).queryByLabelText("한글 읽기"),
      ).not.toBeInTheDocument();
      expect(within(suffix!).getByText("씨")).toBeInTheDocument();
    },
  );

  test("겹친 이름 구간에 든 단어는 원문 순서상 앞선 구간의 종류 하나만 단다", async () => {
    // 行く(3-5)는 두 구간에 모두 든다. 응답 순서와 관계없이 먼저 시작하는 구간을 쓴다.
    respondWithTokyo([
      { start: 3, end: 5, type: "place" },
      { start: 0, end: 5, type: "work" },
    ]);
    render(<App />);
    await send(panelWindowId, "東京へ行った");

    const [, iku] = await wordRows();

    expect(within(iku!).getByText("작품 이름")).toBeInTheDocument();
    expect(within(iku!).queryByText("지명")).not.toBeInTheDocument();
  });

  test.each([[null], [[]]])(
    "이름 구간이 %j이면 배지가 없다",
    async (nameSpans) => {
      respondWithTokyo(nameSpans);
      render(<App />);
      await send(panelWindowId, "東京へ行った");

      for (const row of await wordRows()) {
        expect(row.querySelector(".badge-neutral")).toBeNull();
      }
    },
  );

  test("지정한 이름으로 이름 행이 된 자리에는 배지가 없고, 사전 단어 보기로 바꾸면 단다", async () => {
    respondWithTokyo([{ start: 0, end: 2, type: "place" }]);
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "東京", reading: null },
    ]);
    render(<App />);
    await send(panelWindowId, "東京へ行った");
    await wordRows();
    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(screen.queryByText("지명")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "사전 단어 보기" }));

    expect(screen.getByText("지명")).toBeInTheDocument();
  });
});
