import { useEffect, useState } from "react";
import {
  loadPreference,
  savePreference,
  type Preference,
} from "@/utils/preferences";

// 켜고 끄는 표시 설정 하나. 저장된 값을 읽기 전에는 켜져 있고, 그 전에 사용자가 바꾸면
// 늦게 읽힌 저장값으로 덮어쓰지 않는다.
export function usePreference(key: Preference): [boolean, () => void] {
  const [value, setValue] = useState<boolean>();

  useEffect(() => {
    loadPreference(key).then((stored) =>
      setValue((current) => current ?? stored),
    );
  }, [key]);

  const toggle = () => {
    const next = !(value ?? true);
    setValue(next);
    savePreference(key, next);
  };

  return [value ?? true, toggle];
}
