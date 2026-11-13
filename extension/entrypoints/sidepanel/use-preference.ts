import { useEffect, useState } from "react";

// 확장 저장소에 기억하는 표시 설정 하나. 저장된 값을 읽기 전에는 initial이고, 그 전에 사용자가
// 바꾸면 늦게 읽힌 저장값으로 덮어쓰지 않는다.
export function usePreference<T>(
  load: () => Promise<T>,
  save: (value: T) => Promise<void>,
  initial: T,
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>();

  useEffect(() => {
    load().then((stored) => setValue((current) => current ?? stored));
  }, [load]);

  const change = (next: T) => {
    setValue(next);
    save(next);
  };

  return [value ?? initial, change];
}
