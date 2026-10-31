import { useEffect, useState } from "react";
import { loadTheme, saveTheme, type Theme } from "@/utils/preferences";

// 테마 버튼(#296): 처음에는 브라우저 설정을 따르고, 누르면 지금 보이는 테마의 반대로 바꿔 기억한다.
// 저장값을 읽기 전에 사용자가 바꾸면 늦게 읽힌 저장값으로 덮어쓰지 않는다.
const DARK_QUERY = "(prefers-color-scheme: dark)";

const systemTheme = (): Theme =>
  globalThis.matchMedia?.(DARK_QUERY).matches ? "dark" : "light";

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

export function ThemeButton() {
  // chosen: 이 패널에서 고르거나 저장소에서 읽은 테마. 없으면 브라우저 설정을 따른다.
  const [chosen, setChosen] = useState<Theme | null>(null);
  // 고르기 전에는 브라우저 설정을 따르고, 설정이 바뀌면 버튼도 따라 바뀐다.
  const [system, setSystem] = useState<Theme>(systemTheme);

  useEffect(() => {
    const query = globalThis.matchMedia?.(DARK_QUERY);
    if (!query?.addEventListener) return;
    const changed = () => setSystem(systemTheme());
    query.addEventListener("change", changed);
    return () => query.removeEventListener("change", changed);
  }, []);

  useEffect(() => {
    loadTheme().then((stored) => {
      if (!stored) return;
      setChosen((current) => {
        if (current) return current;
        apply(stored);
        return stored;
      });
    });
  }, []);

  const theme = chosen ?? system;
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setChosen(next);
    apply(next);
    saveTheme(next);
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
        width="18"
        height="18"
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
