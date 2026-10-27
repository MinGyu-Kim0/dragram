import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import type { PatternConnection } from "@/utils/api";
import { fetchConnection } from "@/utils/connections";
import { GrammarCards, HighlightedText } from "./Grammar";

vi.mock("@/utils/connections", () => ({ fetchConnection: vi.fn() }));
beforeEach(() => {
  vi.mocked(fetchConnection).mockReset();
});

const missingConnection = {
  pattern_id: 1,
  text: null,
  review_status: null,
  filled: false,
};
const filledConnection: PatternConnection = {
  ...missingConnection,
  text: "동사 て형 + いる",
  review_status: "pending",
  filled: true,
};

test("접속 형태를 기다리는 중에도 기존 카드와 설명은 즉시 보인다", async () => {
  let finish!: (value: PatternConnection) => void;
  vi.mocked(fetchConnection).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const { container } = render(
    <GrammarCards
      text="食べています"
      grammar={[
        { ...teiru, review_status: "approved", connection: missingConnection },
      ]}
      selection={{ start: 0, end: 7 }}
    />,
  );

  expect(container.querySelector(".grammar-chip")).toHaveTextContent("ている");
  expect(screen.getByText(teiru.explanation_ko)).toBeInTheDocument();
  expect(screen.queryByText("접속:", { exact: false })).not.toBeInTheDocument();
  expect(fetchConnection).toHaveBeenCalledWith(1);

  await act(async () => finish(filledConnection));

  const note = screen.getByText("접속:", { exact: false });
  expect(note).toHaveTextContent("동사 て형 + いる");
  expect(within(note).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(screen.getByText(teiru.explanation_ko)).toBeInTheDocument();
});

test("저장된 접속 형태는 호출 없이 바로 보여 준다", () => {
  render(
    <GrammarCards
      text="食べています"
      grammar={[{ ...teiru, connection: filledConnection }]}
      selection={{ start: 0, end: 7 }}
    />,
  );

  expect(screen.getByText("접속:", { exact: false })).toHaveTextContent(
    "동사 て형 + いる",
  );
  expect(fetchConnection).not.toHaveBeenCalled();
  expect(screen.getAllByText("AI 생성·미검수")).toHaveLength(1);
});

test("접속 형태 생성에 실패해도 기존 설명은 유지한다", async () => {
  vi.mocked(fetchConnection).mockRejectedValue(new Error("생성 실패"));
  render(
    <GrammarCards
      text="食べています"
      grammar={[{ ...teiru, connection: missingConnection }]}
      selection={{ start: 0, end: 7 }}
    />,
  );

  await act(async () => {});

  expect(screen.getByText(teiru.explanation_ko)).toBeInTheDocument();
  expect(screen.queryByText("접속:", { exact: false })).not.toBeInTheDocument();
});

test("다른 카드로 바뀌면 늦게 온 이전 접속 형태는 표시하지 않는다", async () => {
  let finish!: (value: PatternConnection) => void;
  vi.mocked(fetchConnection).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const { rerender } = render(
    <GrammarCards
      text="食べています"
      grammar={[{ ...teiru, connection: missingConnection }]}
      selection={{ start: 0, end: 7 }}
    />,
  );
  rerender(
    <GrammarCards
      text="食べています"
      grammar={[
        {
          ...teiru,
          connection: {
            pattern_id: 2,
            text: null,
            filled: true,
            review_status: null,
          },
        },
      ]}
      selection={{ start: 0, end: 7 }}
    />,
  );

  await act(async () => finish(filledConnection));

  expect(screen.queryByText("접속:", { exact: false })).not.toBeInTheDocument();
});

const teiru = {
  start: 2,
  end: 4,
  state: "decided" as const,
  pattern_name: "ている",
  name: "진행",
  explanation_ko: "동작이 이어지고 있음을 나타낸다",
  korean_equivalent: null,
  korean_equivalent_review_status: null,
  pos_tags: [],
  function_tags: [],
  function_tags_review_status: null,
  review_status: "pending" as const,
  register: "standard" as const,
  variant_of: null,
};

test("칩은 패턴 이름, 보조 줄은 다른 원문 형태를 보이고 설명과 하이라이트를 유지한다", () => {
  const { container } = render(
    <>
      <HighlightedText
        text="食べています"
        grammar={[teiru]}
        ruby={[]}
        dragHandles={undefined}
      />
      <GrammarCards
        text="食べています"
        grammar={[teiru]}
        selection={{ start: 0, end: 7 }}
      />
    </>,
  );

  expect(container.querySelector(".grammar-chip")).toHaveTextContent("ている");
  expect(screen.getByText("문장 속 형태:", { exact: false })).toHaveTextContent(
    "문장 속 형태: てい",
  );
  expect(screen.getByRole("heading", { name: "진행" })).toBeInTheDocument();
  expect(
    screen.getByText("동작이 이어지고 있음을 나타낸다"),
  ).toBeInTheDocument();
  expect(container.querySelector("mark")).toHaveTextContent("てい");
});

test("원문과 패턴 이름이 같으면 보조 줄을 생략한다", () => {
  render(
    <GrammarCards
      text="食べている"
      grammar={[{ ...teiru, end: 5 }]}
      selection={{ start: 0, end: 5 }}
    />,
  );

  expect(
    screen.queryByText("문장 속 형태:", { exact: false }),
  ).not.toBeInTheDocument();
});

test.each([false, true])(
  "확인 중 카드도 패턴 이름과 원문 형태를 함께 보인다(설명 있음: %s)",
  (hasUsage) => {
    const { container } = render(
      <GrammarCards
        text="食べています"
        grammar={[]}
        checking={[
          {
            start: 2,
            end: 4,
            pattern_name: "ている",
            candidates: [{ name: "진행", review_status: "pending" }],
            usage: hasUsage ? teiru : null,
          },
        ]}
        selection={{ start: 0, end: 7 }}
      />,
    );

    expect(container.querySelector(".grammar-chip")).toHaveTextContent(
      "ている",
    );
    expect(
      screen.getByText("문장 속 형태:", { exact: false }),
    ).toHaveTextContent("문장 속 형태: てい");
    expect(screen.getByText("확인 중")).toBeInTheDocument();
  },
);
