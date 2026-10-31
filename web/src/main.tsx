import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App.tsx";
import "./index.css";

// 글꼴 선언 CSS가 커서(약 270KB gzip) 첫 화면을 막지 않게 따로 불러온다. 오기 전에는 시스템 글꼴로 보인다.
void import("./fonts");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
