import type { HighlightStyle } from "@/utils/preferences";

const HIGHLIGHT_STYLES: [HighlightStyle, string][] = [
  ["marker", "형광펜"],
  ["underline", "밑줄"],
];

// 원문 위 표시 설정: 후리가나 켜고 끄기, 형광펜 모양 고르기
export function DisplayToggles({
  showRuby,
  onToggleRuby,
  highlightStyle,
  onHighlightStyleChange,
}: {
  showRuby: boolean;
  onToggleRuby: () => void;
  highlightStyle: HighlightStyle;
  onHighlightStyleChange: (style: HighlightStyle) => void;
}) {
  return (
    <>
      <button type="button" aria-pressed={showRuby} onClick={onToggleRuby}>
        후리가나
      </button>
      <div role="group" aria-label="형광펜 모양" className="style-choice">
        {HIGHLIGHT_STYLES.map(([style, label]) => (
          <button
            key={style}
            type="button"
            aria-pressed={highlightStyle === style}
            onClick={() => onHighlightStyleChange(style)}
          >
            {label}
          </button>
        ))}
      </div>
    </>
  );
}
