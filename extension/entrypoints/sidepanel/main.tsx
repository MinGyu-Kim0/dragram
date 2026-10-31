import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { loadTheme } from "@/utils/preferences";
import App from "./App";
import "./style.css";

// 고른 테마를 첫 화면 전에 건다(#296). 패널은 인라인 스크립트를 쓸 수 없어 저장소를 읽은 뒤 그린다.
loadTheme()
  .then((theme) => {
    if (theme) document.documentElement.dataset.theme = theme;
  })
  .catch(() => {})
  .finally(() =>
    createRoot(document.getElementById("root")!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    ),
  );
