import { afterEach, expect, test, vi } from "vitest";
import { AnalysisFailed, analyzeSentence } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

// 바이트 조각을 차례로 흘려보내는 응답
function chunked(chunks: Uint8Array[]) {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "application/x-ndjson" } },
  );
}

test("줄과 글자가 조각 경계에서 잘려 와도 이벤트를 읽는다", async () => {
  const bytes = new TextEncoder().encode(
    [
      { type: "translation", translation_ko: "학생", ruby: [] },
      { type: "analysis", translation_ko: "학생", grammar: [], words: [] },
    ]
      .map((event) => JSON.stringify(event) + "\n")
      .join(""),
  );
  // "학"(3바이트) 가운데와 첫 줄 가운데에서 자른다.
  const cut = bytes.indexOf(0xed) + 1;
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        chunked([bytes.slice(0, cut), bytes.slice(cut, 60), bytes.slice(60)]),
      ),
  );
  const translations: string[] = [];

  const analysis = await analyzeSentence("学生", (translation) =>
    translations.push(translation.translation_ko),
  );

  expect(translations).toEqual(["학생"]);
  expect(analysis.translation_ko).toBe("학생");
});

test("번역을 받은 뒤 스트림이 끊기면 받은 번역과 함께 실패한다", async () => {
  const line = JSON.stringify({
    type: "translation",
    translation_ko: "학생",
    ruby: [],
  });
  let sent = false;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        // 첫 조각을 읽힌 다음 읽기에서 연결이 끊긴다. 오류를 바로 내면 읽지 않은
        // 조각까지 버려지므로 읽을 때마다 하나씩 준다.
        new ReadableStream<Uint8Array>({
          pull(controller) {
            if (sent) {
              controller.error(new TypeError("network error"));
            } else {
              sent = true;
              controller.enqueue(new TextEncoder().encode(line + "\n"));
            }
          },
        }),
        { status: 200, headers: { "Content-Type": "application/x-ndjson" } },
      ),
    ),
  );

  const failure = await analyzeSentence("学生", () => {}).catch((e) => e);

  expect(failure).toBeInstanceOf(AnalysisFailed);
  expect(failure.translation).toEqual({ translation_ko: "학생", ruby: [] });
});

test("확정 문법이 오면 onEarlyGrammar를 부르고, 실패하면 받은 문법을 함께 싣는다", async () => {
  const item = {
    start: 3,
    end: 6,
    name: "진행",
    explanation_ko: "설명",
    review_status: "approved",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        [
          { type: "grammar", grammar: [item] },
          { type: "error", error: "ANALYSIS:FAILED" },
        ]
          .map((event) => JSON.stringify(event) + "\n")
          .join(""),
        { status: 200, headers: { "Content-Type": "application/x-ndjson" } },
      ),
    ),
  );
  const received: unknown[] = [];

  const failure = await analyzeSentence(
    "彼が来ている",
    () => {},
    (grammar) => received.push(grammar),
  ).catch((e) => e);

  expect(received).toEqual([[item]]);
  expect(failure).toBeInstanceOf(AnalysisFailed);
  expect(failure.earlyGrammar).toEqual([item]);
  expect(failure.translation).toBeUndefined();
});
