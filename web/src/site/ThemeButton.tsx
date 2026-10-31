import { useState } from "react";

// 테마 버튼(#296): 처음에는 브라우저 설정을 따르고, 누르면 지금 보이는 테마의 반대로 바꿔 기억한다.
// 기억한 값은 index.html이 첫 화면을 그리기 전에 <html data-theme>으로 다시 건다.
const KEY = "dragram-theme";

type Theme = "light" | "dark";

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    // 저장소를 막아 둔 브라우저에서도 화면은 그린다.
    return null;
  }
}

const systemTheme = (): Theme =>
  globalThis.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";

function ThemeButton() {
  const [theme, setTheme] = useState<Theme>(
    () => storedTheme() ?? systemTheme(),
  );

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // 기억하지 못해도 이 화면에서는 바뀐다.
    }
  };

  return (
    <button
      type="button"
      className="theme-button"
      aria-label="다크 모드"
      aria-pressed={theme === "dark"}
      onClick={toggle}
    >
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        aria-hidden="true"
      >
        {theme === "dark" ? (
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        ) : (
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
          </>
        )}
      </svg>
    </button>
  );
}

export default ThemeButton;
