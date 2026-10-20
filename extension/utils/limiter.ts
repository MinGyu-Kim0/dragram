// 비동기 작업을 동시에 max개까지만 돌린다. 진행 중인 작업은 끝날 때까지 개수에 들어가고,
// 아직 시작하지 않은 작업은 cancelled()가 참이 되면 시작하지 않고 버린다.
export interface Limiter {
  schedule<T>(task: () => Promise<T>, cancelled: () => boolean): Promise<T>;
}

export function createLimiter(max: number): Limiter {
  let running = 0;
  const queue: { start: () => void; cancelled: () => boolean }[] = [];

  const pump = () => {
    while (running < max && queue.length > 0) {
      const next = queue.shift()!;
      if (next.cancelled()) continue;
      running += 1;
      next.start();
    }
  };

  return {
    schedule(task, cancelled) {
      // 버린 작업의 Promise는 끝나지 않는다. 버린 쪽은 결과를 기다리지 않는다.
      return new Promise((resolve, reject) => {
        queue.push({
          cancelled,
          start: () =>
            task()
              .then(resolve, reject)
              .finally(() => {
                running -= 1;
                pump();
              }),
        });
        pump();
      });
    },
  };
}
