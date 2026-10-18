import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import App from "./App";

test("사이드 패널에 앱 이름을 제목으로 보여준다", () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "Dragram" })).toBeInTheDocument();
});
