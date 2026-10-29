// 키(창)마다 가장 최근에 시작한 작업인지 알려 준다. 늦게 끝난 이전 작업이 최신 결과를
// 덮어쓰지 않게 한다. start(key)는 그 작업이 아직 최신인지 묻는 함수를 돌려준다.
export function latestPerKey(): (key: number) => () => boolean {
  const latest = new Map<number, number>();
  let counter = 0;
  return (key) => {
    counter += 1;
    const ticket = counter;
    latest.set(key, ticket);
    return () => latest.get(key) === ticket;
  };
}
