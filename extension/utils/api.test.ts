import { afterEach, expect, test, vi } from "vitest";
import { analyzeSentence } from "./api";

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
