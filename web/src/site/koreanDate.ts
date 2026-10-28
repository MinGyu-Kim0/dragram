/** 시행일(YYYY-MM-DD)을 '2026년 10월 28일'로 쓴다. */
export function koreanDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}
