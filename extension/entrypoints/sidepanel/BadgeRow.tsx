// 문법·단어 카드의 첫 줄(배지 줄): 왼쪽에 상태 배지, 오른쪽에 '드래그한 부분'. 둘 다 없으면 줄을
// 그리지 않는다(DESIGN.md 3장).
export function BadgeRow({
  pending = false,
  translated = false,
  colloquial = false,
  name,
  dragged = false,
}: {
  pending?: boolean;
  translated?: boolean;
  colloquial?: boolean;
  // 이름 구간의 종류 이름(사람 이름 등, #184). 검수 흐름이 없는 문장 안 판단이라 중립 배지다.
  name?: string;
  dragged?: boolean;
}) {
  if (!pending && !translated && !colloquial && !name && !dragged) return null;
  return (
    <div className="card-badges">
      {pending && <span className="badge-warn">AI 생성·미검수</span>}
      {translated && <span className="badge-warn">AI 번역</span>}
      {colloquial && <span className="badge-neutral">회화체</span>}
      {name && <span className="badge-neutral">{name}</span>}
      {dragged && <span className="card-meta">드래그한 부분</span>}
    </div>
  );
}
