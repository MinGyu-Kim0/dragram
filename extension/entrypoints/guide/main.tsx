import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { loadTheme } from "@/utils/preferences";
import { Guide } from "./Guide";
import "@fontsource/jua/latin-400.css";
import "../sidepanel/style.css";
import "./guide.css";

// 패널과 같은 테마로 그린다(#296).
loadTheme()
  .then((theme) => {
    if (theme) document.documentElement.dataset.theme = theme;
  })
  .catch(() => {})
  .finally(() =>
    createRoot(document.getElementById("root")!).render(
      <StrictMode>
        <Guide />
      </StrictMode>,
    ),
  );
