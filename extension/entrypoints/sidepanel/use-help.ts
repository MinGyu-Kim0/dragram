import { useEffect, useRef, useState, type RefObject } from "react";
import { loadHelpSeen, saveHelpSeen } from "@/utils/preferences";

// 도움말(#365) 열림 상태. ready(로그인했고 보이는 문장이 없음)가 되면, 닫은 적이 없을 때 한 번
// 저절로 연다. 기다리던 문장의 결과를 가리지 않게 문장이 있으면 열지 않는다. 저장값을 읽기 전에
// 사용자가 열거나 닫았으면 늦게 읽힌 값으로 바꾸지 않는다. 닫으면 포커스를 button으로 돌린다.
export function useHelp(
  ready: boolean,
  button: RefObject<HTMLButtonElement | null>,
) {
  const [open, setOpen] = useState(false);
  const touched = useRef(false);

  useEffect(() => {
    if (!ready) return;
    loadHelpSeen().then((seen) => {
      if (!seen && !touched.current) setOpen(true);
    });
  }, [ready]);

  const close = () => {
    touched.current = true;
    setOpen(false);
    saveHelpSeen();
    button.current?.focus();
  };
  const toggle = () => {
    if (open) return close();
    touched.current = true;
    setOpen(true);
  };
  return { open, close, toggle };
}
