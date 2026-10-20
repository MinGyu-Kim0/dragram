// 문장 안에서 실제로 드래그한 범위. 원문 기준 UTF-16 위치 [start, end)
export interface DragRange {
  start: number;
  end: number;
}

interface Span {
  start: number;
  end: number;
}

// 드래그 범위와 겹치는 항목을 먼저, 나머지를 그 뒤에 둔다. 각 묶음 안의 순서는 그대로다.
// 범위 끝에 닿기만 하는 항목은 겹친 것으로 보지 않는다.
export function draggedFirst<T extends Span>(
  items: T[],
  selection: DragRange,
): { item: T; dragged: boolean }[] {
  const marked = items.map((item) => ({
    item,
    dragged: item.start < selection.end && selection.start < item.end,
  }));
  return [
    ...marked.filter((entry) => entry.dragged),
    ...marked.filter((entry) => !entry.dragged),
  ];
}
