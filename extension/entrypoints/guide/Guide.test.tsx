import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { Guide } from "./Guide";
import { STEPS } from "./steps";

const dialog = () => screen.getByRole("dialog");
const progress = () => within(dialog()).getByText(/^\d+ \/ \d+$/);

beforeEach(() => {
  vi.stubGlobal("close", vi.fn());
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("첫 단계부터 보이고, 다음·이전과 화살표 키로 넘긴다", () => {
  render(<Guide />);

  expect(dialog()).toHaveAccessibleName(STEPS[0]!.title);
  expect(progress()).toHaveTextContent(`1 / ${STEPS.length}`);
  expect(screen.queryByRole("button", { name: "이전" })).toBeDisabled();

  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  expect(dialog()).toHaveAccessibleName(STEPS[1]!.title);
  fireEvent.keyDown(window, { key: "ArrowRight" });
  expect(progress()).toHaveTextContent(`3 / ${STEPS.length}`);
  fireEvent.keyDown(window, { key: "ArrowLeft" });
  fireEvent.click(screen.getByRole("button", { name: "이전" }));
  expect(progress()).toHaveTextContent(`1 / ${STEPS.length}`);
});

test("모든 단계의 강조 대상이 장면 안에 있다", () => {
  const { container } = render(<Guide />);

  for (const step of STEPS) {
    const scene = container.querySelector(".guide-scene")!;
    expect(scene.querySelector(step.target), step.title).not.toBeNull();
    if (step !== STEPS.at(-1)) {
      fireEvent.click(screen.getByRole("button", { name: "다음" }));
    }
  }
});

test("마지막 단계의 '시작하기'와 건너뛰기·Esc는 가이드 탭을 닫는다", () => {
  render(<Guide />);

  fireEvent.click(screen.getByRole("button", { name: "건너뛰기" }));
  fireEvent.keyDown(window, { key: "Escape" });
  for (let i = 1; i < STEPS.length; i++) {
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
  }
  expect(
    screen.queryByRole("button", { name: "다음" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "시작하기" }));

  expect(close).toHaveBeenCalledTimes(3);
});

test("장면은 실제 카드로 그리고 미검수 배지가 있으며, 눌러도 아무것도 보내지 않는다", () => {
  const { container } = render(<Guide />);
  const scene = container.querySelector<HTMLElement>(".guide-scene")!;

  expect(scene).toHaveAttribute("inert");
  expect(within(scene).getAllByText("AI 생성·미검수").length).toBeGreaterThan(
    0,
  );
  for (const button of within(scene).queryAllByRole("button", {
    hidden: true,
  })) {
    fireEvent.click(button);
  }

  expect(fetch).not.toHaveBeenCalled();
});
