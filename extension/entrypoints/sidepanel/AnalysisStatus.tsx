// 실패 문구 바로 옆에 두는 다시 시도 버튼
export function RetryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <button type="button" className="retry" onClick={onRetry}>
      다시 시도
    </button>
  );
}

// 문법·단어 분석을 기다리는 중. 탭 자리(탭이 생긴 뒤에는 탭 바로 밑)에 둔다.
export function AnalyzingStatus({ className = "" }: { className?: string }) {
  return (
    <p role="status" aria-label="분석 중" className={`analyzing ${className}`}>
      <span aria-hidden="true" className="spinner" />
      분석 중…
    </p>
  );
}
