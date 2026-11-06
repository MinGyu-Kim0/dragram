// 사이드 패널 App 테스트 파일들이 함께 쓰는 가짜 응답·조회 도우미. 이 모듈을 불러오면 패널 준비와
// 뒷정리(beforeEach·afterEach)도 함께 걸린다. vi.mock은 파일마다 끌어올려지므로 테스트 파일에 둔다.
import { afterEach, beforeEach, vi } from "vitest";
import { requestAnalysis } from "@/utils/analysis-request";
import { screen } from "@testing-library/react";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { saveToken } from "@/utils/auth";
import { fetchNames, removeName, saveName } from "@/utils/names";
import { fetchMyItems, saveMyItem } from "@/utils/my-items";

export function respondWith(status: number, body: object) {
  // 응답 본문은 한 번만 읽을 수 있어 요청마다 새로 만든다.
  const fetchMock = vi.fn((_url: string, _init: RequestInit) =>
    Promise.resolve(json(status, body)),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// 문장들을 분석 요청으로 넣는다.
export function send(windowId: number, ...texts: string[]) {
  return requestAnalysis(
    windowId,
    texts.map((text) => ({ text })),
  );
}

// 문장마다 다른 응답을 준다. 정하지 않은 문장은 응답하지 않는다(분석 중으로 남는다).
export function respondPerSentence(
  responses: Record<string, () => Promise<Response> | Response>,
) {
  const fetchMock = vi.fn((_url: string, init: RequestInit) => {
    const { text } = JSON.parse(init.body as string) as { text: string };
    const respond = responses[text];
    return respond
      ? Promise.resolve(respond())
      : new Promise<Response>(() => {});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export interface AnalysisBody {
  translation_ko: string;
  grammar: unknown[];
  words: unknown[];
  ruby?: unknown[];
}

// 성공 응답은 서버처럼 줄 단위 JSON 이벤트 두 줄(번역 → 문법·단어)로 한 번에 준다.
// 테스트가 정하지 않은 루비는 빈 목록으로 채운다. 실패 응답은 JSON 본문 그대로다.
export function json(status: number, body: object) {
  if (status !== 200) {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }
  const { ruby = [], ...result } = body as AnalysisBody;
  return ndjson([
    { type: "translation", translation_ko: result.translation_ko, ruby },
    { type: "analysis", ...result },
  ]);
}

export function ndjson(events: object[]) {
  return new Response(
    events.map((event) => JSON.stringify(event) + "\n").join(""),
    {
      status: 200,
      headers: { "Content-Type": "application/x-ndjson" },
    },
  );
}

// 이벤트를 테스트가 정한 때에 한 줄씩 흘려보내는 응답
export function streamed() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  const encoder = new TextEncoder();
  return {
    response: new Response(body, {
      status: 200,
      headers: { "Content-Type": "application/x-ndjson" },
    }),
    push(event: object) {
      controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
    },
    end() {
      controller.close();
    },
  };
}

export function analysis(translation: string) {
  return { translation_ko: translation, grammar: [], words: [] };
}

// 사이드 패널이 열린 창
export let panelWindowId: number;

export function grammarItem(
  start: number,
  end: number,
  name: string,
  pattern_name = "ている",
) {
  return {
    start,
    end,
    pattern_name,
    state: "decided",
    name,
    explanation_ko: `${name} 설명`,
    korean_equivalent: null,
    korean_equivalent_review_status: null,
    pos_tags: [],
    function_tags: [],
    function_tags_review_status: null,
    review_status: "pending",
    register: "standard",
    variant_of: null,
  };
}

// 사전 단어. sense를 null로 주면 뜻을 준비하는 중인 단어다. 영어 뜻은 `${표제} gloss`, 한국어 뜻은
// 검수된 `${표제} 뜻`이다.
export function wordItem(
  start: number,
  end: number,
  form: string,
  reading: string,
  sense: object | null = {},
  tags: string[] = ["noun"],
) {
  return {
    start,
    end,
    dictionary_form: form,
    reading,
    tags,
    in_dictionary: true,
    sense: sense && {
      tags: [],
      gloss_en: [`${form} gloss`],
      origin: "jmdict",
      status: "approved",
      meaning_ko: `${form} 뜻`,
      meaning_status: "reviewed",
      ...sense,
    },
  };
}

export function rubyItem(start: number, end: number, reading: string) {
  return { start, end, reading };
}

// 원문에 달린 루비를 [밑글자, 읽기]로 읽는다.
export function rubies(): [string, string][] {
  return [...document.querySelectorAll(".original ruby")].map((ruby) => {
    const rt = ruby.querySelector("rt")!.textContent!;
    return [ruby.textContent!.slice(0, -rt.length), rt];
  });
}

export function approvedGrammarItem(start: number, end: number, name: string) {
  return { ...grammarItem(start, end, name), review_status: "approved" };
}

// 후보가 모두 검수된 판별 대상 구간
export function checkingItem(start: number, end: number, ...names: string[]) {
  return {
    start,
    end,
    pattern_name: "ている",
    candidates: names.map((name) => ({ name, review_status: "approved" })),
  };
}

export function cardOf(name: string) {
  return screen.getByRole("heading", { name }).closest("li")!;
}

// 구성 문법(#65): 긴 문법 안에 완전히 들어가는 문법은 서버가 그 항목의 parts로 보낸다.
// 문장: 食べてしまった (食べ 0-2 / て 2-3 / しまっ 3-6 / た 6-7)
export function withParts(item: object, ...parts: object[]) {
  return { ...item, parts };
}

beforeEach(async () => {
  fakeBrowser.reset();
  const panelWindow = await fakeBrowser.windows.create({ focused: true });
  panelWindowId = panelWindow!.id!;
  // 웹에서 연결한 상태로 시작한다(#109).
  await saveToken("extension-token");
  vi.mocked(fetchNames).mockReset().mockResolvedValue([]);
  vi.mocked(fetchMyItems).mockReset().mockResolvedValue([]);
  vi.mocked(saveMyItem).mockReset();
  vi.mocked(saveName).mockReset();
  vi.mocked(removeName).mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete document.documentElement.dataset.theme;
});
