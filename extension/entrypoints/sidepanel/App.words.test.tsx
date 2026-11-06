import { describe, expect, test, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import App from "./App";
import { fetchNames } from "@/utils/names";
import {
  grammarItem,
  json,
  ndjson,
  panelWindowId,
  respondPerSentence,
  respondWith,
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

test("고른 뜻이 '보통 가나로 씀'이고 사전형에 한자가 있으면 읽기를 표제로, 사전형을 회색 글자로 보인다", async () => {
  respondWith(200, {
    translation_ko: "많은 책과 종이가 있다.",
    grammar: [],
    words: [
      wordItem(0, 2, "沢山", "たくさん", { tags: ["uk"] }),
      wordItem(3, 4, "本", "ほん"),
      wordItem(5, 6, "紙", "かみ", null),
      wordItem(7, 9, "ある", "ある", { tags: ["uk"] }, ["verb"]),
    ],
  });
  render(<App />);
  await send(panelWindowId, "沢山の本と紙がある");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 4" }));

  const rows = within(screen.getByRole("list", { name: "단어" }))
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
  expect(
    rows.map((row) => [
      within(row).getByRole("heading").textContent,
      row.querySelector(".word-reading")!.textContent,
    ]),
  ).toEqual([
    ["たくさん", "沢山"],
    ["本", "ほん"],
    ["紙", "かみ"],
    ["ある", "ある"],
  ]);
});

test("같은 단어도 자리마다 고른 뜻의 자동사·타동사 태그를 보이고, 예외 1그룹 동사에 그 태그를 보인다", async () => {
  respondWith(200, {
    translation_ko: "날이 밝아 돌아가서 문을 연다.",
    grammar: [],
    words: [
      wordItem(2, 4, "開ける", "あける", { tags: ["intransitive"] }, [
        "verb",
        "group2",
      ]),
      wordItem(5, 7, "帰る", "かえる", {}, ["verb", "group1_exception"]),
      wordItem(11, 14, "開ける", "あける", { tags: ["transitive"] }, [
        "verb",
        "group2",
      ]),
    ],
  });
  render(<App />);
  await send(panelWindowId, "夜が明けて帰るとドアを開ける");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 3" }));

  const rows = within(screen.getByRole("list", { name: "단어" }))
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
  expect(
    rows.map((row) =>
      within(within(row).getByRole("list", { name: "태그" }))
        .getAllByRole("listitem")
        .map((tag) => tag.textContent),
    ),
  ).toEqual([
    ["동사", "2그룹", "자동사"],
    ["동사", "예외 1그룹"],
    ["동사", "2그룹", "타동사"],
  ]);
});

test("읽기가 여럿인 단어는 대표 읽기를 보이고, 누르면 그 단어만 나머지 읽기까지 펼친다", async () => {
  respondWith(200, {
    translation_ko: "일본에서 학생이다.",
    grammar: [],
    words: [
      { ...wordItem(0, 2, "日本", "にほん"), other_readings: ["にっぽん"] },
      wordItem(3, 5, "学生", "がくせい"),
    ],
  });
  render(<App />);
  await send(panelWindowId, "日本で学生だ");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));
  const [nihon, gakusei] = within(screen.getByRole("list", { name: "단어" }))
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
  expect(within(nihon!).getByText("にほん")).toBeInTheDocument();
  expect(
    within(gakusei!).queryByRole("button", { name: /다른 읽기/ }),
  ).toBeNull();

  fireEvent.click(
    within(nihon!).getByRole("button", { name: "다른 읽기 1개 보기" }),
  );

  expect(within(nihon!).getByText("にほん・にっぽん")).toBeInTheDocument();
  fireEvent.click(
    within(nihon!).getByRole("button", { name: "다른 읽기 접기" }),
  );
  expect(within(nihon!).getByText("にほん")).toBeInTheDocument();
});

test("탭에 문법과 단어 개수를 보이고, 처음에는 문법 탭을 보인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は"), grammarItem(4, 6, "정중 です")],
    words: [wordItem(2, 4, "学生", "がくせい")],
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  const tabs = await screen.findAllByRole("tab");
  expect(tabs.map((tab) => tab.textContent)).toEqual(["문법 2", "단어 1"]);
  expect(screen.getByRole("tab", { name: "문법 2" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("heading", { name: "주제 は" })).toBeInTheDocument();
  expect(screen.queryByText("学生 뜻")).not.toBeInTheDocument();
});

test("단어 탭에 단어마다 사전형, 읽기, 태그, 한국어 뜻을 원문 순서대로 보이고 JMdict 출처를 단다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생으로서 먹고 있다.",
    grammar: [grammarItem(1, 2, "주제 は")],
    // 응답 순서와 상관없이 원문 순서대로 보인다.
    words: [
      wordItem(
        5,
        7,
        "食べる",
        "たべる",
        { tags: ["transitive"], gloss_en: ["to eat", "to live on"] },
        ["verb", "group2"],
      ),
      wordItem(0, 1, "私", "わたし", {}, ["pronoun"]),
    ],
  });
  render(<App />);
  await send(panelWindowId, "私は学生で食べている");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));

  expect(screen.getByRole("tab", { name: "단어 2" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    screen.queryByRole("heading", { name: "주제 は" }),
  ).not.toBeInTheDocument();
  const rows = within(screen.getByRole("list", { name: "단어" })).getAllByRole(
    "listitem",
  );
  const words = rows.filter((row) => row.classList.contains("word-row"));
  expect(
    words.map((row) => within(row).getByRole("heading").textContent),
  ).toEqual(["私", "食べる"]);
  expect(within(words[1]!).getByText("たべる")).toBeInTheDocument();
  expect(within(words[1]!).getByText("食べる 뜻")).toBeInTheDocument();
  // 영어 뜻은 보이지 않는다(LLM 입력과 admin에만 쓴다).
  expect(screen.queryByText(/to eat/)).not.toBeInTheDocument();
  // 단어 전체 태그 뒤에 고른 뜻의 태그를 보인다.
  expect(
    within(within(words[1]!).getByRole("list", { name: "태그" }))
      .getAllByRole("listitem")
      .map((tag) => tag.textContent),
  ).toEqual(["동사", "2그룹", "타동사"]);
  // 검수된 JMdict 뜻에는 배지가 없고 출처 각주가 있다.
  for (const row of words) {
    expect(within(row).queryByText("AI 생성·미검수")).not.toBeInTheDocument();
    expect(within(row).queryByText("AI 번역")).not.toBeInTheDocument();
  }
  expect(screen.getByRole("link", { name: "JMdict" })).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "CC BY-SA 4.0" }),
  ).toBeInTheDocument();
});

test("뜻의 출처·검수 상태에 따라 'AI 생성·미검수'와 'AI 번역' 배지를 단다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [],
    words: [
      wordItem(0, 1, "一", "いち", { origin: "llm", status: "pending" }),
      wordItem(1, 2, "二", "に", { meaning_ko: "둘", meaning_status: "ai" }),
      wordItem(2, 3, "三", "さん", {
        meaning_ko: "셋",
        meaning_status: "reviewed",
      }),
    ],
  });
  render(<App />);
  await send(panelWindowId, "一二三");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 3" }));

  const [llm, translated, reviewed] = within(
    screen.getByRole("list", { name: "단어" }),
  )
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
  expect(within(llm!).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(within(translated!).getByText("둘")).toBeInTheDocument();
  expect(within(translated!).getByText("AI 번역")).toBeInTheDocument();
  expect(within(reviewed!).getByText("셋")).toBeInTheDocument();
  expect(within(reviewed!).queryByText("AI 번역")).not.toBeInTheDocument();
});

test("관리자가 승인한 LLM 뜻에는 'AI 생성·미검수'도 'AI 번역'도 달지 않는다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [],
    words: [
      wordItem(0, 1, "一", "いち", {
        origin: "llm",
        status: "approved",
        meaning_ko: "하나",
        meaning_status: "ai",
      }),
    ],
  });
  render(<App />);
  await send(panelWindowId, "一");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 1" }));

  expect(screen.getByText("하나")).toBeInTheDocument();
  expect(screen.queryByText("AI 생성·미검수")).not.toBeInTheDocument();
  expect(screen.queryByText("AI 번역")).not.toBeInTheDocument();
});

test("LLM보다 먼저 온 단어는 탭에 바로 보이고, 뜻을 준비하는 중인 단어는 분석이 오면 채운다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "学生が開いた");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [],
    words: [
      wordItem(0, 2, "学生", "がくせい"),
      wordItem(3, 5, "開く", "ひらく", null, ["verb", "group1"]),
    ],
  });

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));
  expect(
    screen.getByRole("status", { name: "번역을 불러오는 중" }),
  ).toBeInTheDocument();
  expect(screen.getByText("学生 뜻")).toBeInTheDocument();
  expect(
    screen.getByRole("status", { name: "뜻을 준비하는 중" }),
  ).toBeInTheDocument();
  // 문법은 아직 오지 않아 '문법 요소 없음'이라고 단정하지 않는다.
  fireEvent.click(screen.getByRole("tab", { name: "문법 0" }));
  expect(screen.getByRole("status", { name: "분석 중" })).toBeInTheDocument();
  expect(screen.queryByText("문법 요소 없음")).not.toBeInTheDocument();

  stream.push({
    type: "translation",
    translation_ko: "학생이 열었다",
    ruby: [],
  });
  stream.push({
    type: "analysis",
    translation_ko: "학생이 열었다",
    grammar: [],
    words: [
      wordItem(0, 2, "学生", "がくせい"),
      wordItem(3, 5, "開く", "ひらく", { meaning_ko: "열다" }),
    ],
  });
  stream.end();

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));
  expect(await screen.findByText("열다")).toBeInTheDocument();
  expect(
    screen.queryByRole("status", { name: "뜻을 준비하는 중" }),
  ).not.toBeInTheDocument();
});

test("단어 뜻 앞에 '뜻' 라벨을 달고, 준비 중·실패 문구에는 달지 않는다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [],
    words: [
      wordItem(0, 1, "一", "いち"),
      wordItem(1, 2, "二", "に", { meaning_ko: null, meaning_status: "ai" }),
      wordItem(2, 3, "三", "さん", {
        meaning_ko: null,
        meaning_status: "failed",
      }),
    ],
  });
  render(<App />);
  await send(panelWindowId, "一二三");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 3" }));

  const [meaning, waiting, failed] = within(
    screen.getByRole("list", { name: "단어" }),
  )
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
  expect(
    within(within(meaning!).getByText("一 뜻")).getByText("뜻"),
  ).toBeVisible();
  expect(within(waiting!).queryByText("뜻")).toBeNull();
  expect(within(failed!).queryByText("뜻")).toBeNull();
});

test("한국어 뜻이 아직 없으면 준비 중, 만들지 못했으면 실패 문구를 보인다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [],
    words: [
      wordItem(0, 1, "一", "いち", { meaning_ko: null, meaning_status: "ai" }),
      wordItem(1, 2, "二", "に", {
        meaning_ko: null,
        meaning_status: "failed",
      }),
    ],
  });
  render(<App />);
  await send(panelWindowId, "一二");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));

  const [waiting, failed] = within(screen.getByRole("list", { name: "단어" }))
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
  expect(
    within(waiting!).getByRole("status", { name: "뜻을 준비하는 중" }),
  ).toBeInTheDocument();
  expect(
    within(failed!).getByText("뜻을 만들지 못했습니다"),
  ).toBeInTheDocument();
  // 단어 하나의 뜻 실패는 문장 실패가 아니다(표제·읽기·각주는 그대로).
  expect(within(failed!).getByText("に")).toBeInTheDocument();
  expect(screen.queryByText(/gloss/)).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "JMdict" })).toBeInTheDocument();
});

test("LLM이 만든 단어만 있으면 JMdict 출처 각주를 달지 않는다", async () => {
  respondWith(200, {
    translation_ko: "달리고 있다",
    grammar: [],
    words: [
      {
        ...wordItem(0, 2, "走る", "はしる", {
          origin: "llm",
          status: "pending",
          meaning_ko: "달리다",
        }),
        in_dictionary: false,
      },
    ],
  });
  render(<App />);
  await send(panelWindowId, "走っている");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 1" }));

  expect(screen.getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "JMdict" }),
  ).not.toBeInTheDocument();
});

test("분석 전에 온 judged 이벤트로 고른 뜻을 채운다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "本を開いた");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [],
    words: [wordItem(2, 4, "開く", "ひらく", null)],
  });
  stream.push({ type: "translation", translation_ko: "책을 펼쳤다", ruby: [] });
  stream.push({
    type: "judged",
    grammar: [],
    checking: [],
    words: [
      wordItem(2, 4, "開く", "ひらく", {
        meaning_ko: null,
        meaning_status: "ai",
      }),
    ],
  });

  fireEvent.click(await screen.findByRole("tab", { name: "단어 1" }));
  expect(screen.getByText("책을 펼쳤다")).toBeInTheDocument();
  expect(
    screen.getByRole("status", { name: "뜻을 준비하는 중" }),
  ).toBeInTheDocument();

  stream.push({
    type: "judged",
    grammar: [],
    checking: [],
    words: [
      wordItem(2, 4, "開く", "ひらく", {
        meaning_ko: "피다",
        meaning_status: "ai",
      }),
    ],
  });

  expect(await screen.findByText("피다")).toBeInTheDocument();
  expect(screen.getByText("AI 번역")).toBeInTheDocument();
  expect(screen.getByText("책을 펼쳤다")).toBeInTheDocument();
  stream.end();
});

test("먼저 온 단어가 있어도 분석이 실패하면 단어를 지우고 실패를 보인다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        ndjson([
          {
            type: "grammar",
            grammar: [],
            checking: [],
            words: [wordItem(3, 5, "開く", "ひらく", null)],
          },
          { type: "translation", translation_ko: "학생이 열었다", ruby: [] },
          { type: "error", error: "ANALYSIS:FAILED" },
        ]),
      ),
    ),
  );
  render(<App />);

  await send(panelWindowId, "学生が開いた");

  expect(
    await screen.findByText("문법·단어를 분석하지 못했습니다"),
  ).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("status", { name: "뜻을 준비하는 중" }),
  ).not.toBeInTheDocument();
});

describe("같은 단어·같은 뜻인 단어 행 합치기(#211)", () => {
  // 8回と9回に来た: 回가 두 자리(1-2, 4-5), 来る(6-7)
  const TEXT = "8回と9回に来た";

  function respondWithWords(words: object[], nameSpans: object[] | null = []) {
    return respondPerSentence({
      [TEXT]: () =>
        json(200, {
          translation_ko: "8회와 9회에 왔다",
          grammar: [],
          words,
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

  test("사전형·읽기·뜻이 같으면 한 장으로 합치고 개수도 합친 뒤로 센다", async () => {
    respondWithWords([
      wordItem(1, 2, "回", "かい"),
      wordItem(4, 5, "回", "かい"),
      wordItem(6, 7, "来る", "くる"),
    ]);
    render(<App />);
    await send(panelWindowId, TEXT);

    const rows = await wordRows();

    expect(
      rows.map((row) => within(row).getByRole("heading").textContent),
    ).toEqual(["回", "来る"]);
    expect(screen.getByRole("tab", { name: "단어 2" })).toBeInTheDocument();
  });

  test("분석 중에 먼저 온 단어도 같은 규칙으로 합친다", async () => {
    const stream = streamed();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
    render(<App />);
    await send(panelWindowId, TEXT);

    stream.push({
      type: "grammar",
      grammar: [],
      checking: [],
      words: [wordItem(1, 2, "回", "かい"), wordItem(4, 5, "回", "かい")],
    });

    expect(
      await screen.findByRole("tab", { name: "단어 1" }),
    ).toBeInTheDocument();
    expect(await wordRows()).toHaveLength(1);
    stream.end();
  });

  test("뜻이 다르거나 아직 고르지 않은 자리는 따로 둔다", async () => {
    respondWithWords([
      wordItem(1, 2, "回", "かい"),
      wordItem(4, 5, "回", "かい", { meaning_ko: "번" }),
      wordItem(6, 7, "来る", "くる", null),
    ]);
    render(<App />);
    await send(panelWindowId, TEXT);

    expect(await wordRows()).toHaveLength(3);
  });

  test("사전형·뜻이 같아도 표기가 다른 자리(활용형)는 따로 둔다", async () => {
    // 食べた食べる: 食べ(0-2), 食べる(3-6)
    respondPerSentence({
      食べた食べる: () =>
        json(200, {
          translation_ko: "먹었고 먹는다",
          grammar: [],
          words: [
            wordItem(0, 2, "食べる", "たべる"),
            wordItem(3, 6, "食べる", "たべる"),
          ],
          name_spans: [],
        }),
    });
    render(<App />);
    await send(panelWindowId, "食べた食べる");

    expect(await wordRows()).toHaveLength(2);
  });

  test("지정한 이름과 표기가 같은 단어와 이름 종류 배지가 다른 자리는 합치지 않는다", async () => {
    vi.mocked(fetchNames).mockResolvedValue([{ surface: "来", reading: null }]);
    respondWithWords(
      [
        wordItem(1, 2, "回", "かい"),
        wordItem(4, 5, "回", "かい"),
        wordItem(6, 7, "来る", "くる"),
      ],
      [{ start: 4, end: 5, type: "other" }],
    );
    render(<App />);
    await send(panelWindowId, TEXT);

    const rows = await wordRows();

    expect(rows).toHaveLength(3);
    expect(within(rows[1]!).getByText("기타 이름")).toBeInTheDocument();
  });

  test("지정한 이름과 표기가 같은 자리는 뜻이 같아도 자리마다 따로 보인다", async () => {
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "回", reading: "かい" },
    ]);
    respondWithWords(
      [wordItem(1, 2, "回", "かい"), wordItem(4, 5, "回", "かい")],
      [],
    );
    render(<App />);
    await send(panelWindowId, TEXT);

    expect(await wordRows()).toHaveLength(2);
  });
});
