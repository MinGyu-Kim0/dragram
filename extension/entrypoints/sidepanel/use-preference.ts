import { useEffect, useState } from "react";
import {
  loadHighlightStyle,
  loadPreference,
  saveHighlightStyle,
  savePreference,
  type HighlightStyle,
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

// 원문 형광펜 모양(#354). 저장된 값을 읽기 전에는 형광펜이고, 그 전에 사용자가 고르면
// 늦게 읽힌 저장값으로 덮어쓰지 않는다.
export function useHighlightStyle(): [
  HighlightStyle,
  (style: HighlightStyle) => void,
] {
  const [style, setStyle] = useState<HighlightStyle>();

  useEffect(() => {
    loadHighlightStyle().then((stored) =>
      setStyle((current) => current ?? stored),
    );
  }, []);

  const choose = (next: HighlightStyle) => {
    setStyle(next);
    saveHighlightStyle(next);
  };

  return [style ?? "marker", choose];
}
