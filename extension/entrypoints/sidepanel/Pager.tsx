// 여러 문장을 분석했을 때 문장별 페이지를 넘기는 줄(이전 · N / M · 다음)
export function Pager({
  index,
  total,
  onGo,
}: {
  index: number;
  total: number;
  onGo: (index: number) => void;
}) {
  return (
    <nav className="pager" aria-label="문장">
      <button
        type="button"
        aria-label="이전 문장"
        disabled={index === 0}
        onClick={() => onGo(index - 1)}
      >
        ‹
      </button>
      <span>
        {index + 1} / {total}
      </span>
      <button
        type="button"
        aria-label="다음 문장"
        disabled={index === total - 1}
        onClick={() => onGo(index + 1)}
      >
        ›
      </button>
    </nav>
  );
}
