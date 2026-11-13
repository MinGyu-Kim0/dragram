import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { renderWithTheme } from "@/utils/preferences";
import App from "./App";
// 로고 글자(Dragram)에 쓰는 Jua. 웹과 같은 글꼴을 싣되, 확장 크기를 줄이려고 라틴 부분만 넣는다.
import "@fontsource/jua/latin-400.css";
import "./style.css";

renderWithTheme(() =>
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  ),
);
