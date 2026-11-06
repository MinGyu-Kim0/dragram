import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchNames,
  removeName,
  saveName,
  type DesignatedName,
} from "@/utils/names";
import type { LoginGeneration } from "./use-login-generation";

// 지정한 이름(#136). 연결되면 한 번 받고, 지정·해제하면 열린 모든 문장 페이지에 바로 쓴다.
export function useDesignatedNames(
  connected: boolean | undefined,
  generation: LoginGeneration,
) {
  const [list, setList] = useState<DesignatedName[]>([]);
  // 끝난 저장·해제 수. 목록을 받는 사이 바뀌었으면 그 목록은 옛것이라 다시 받는다.
  const edits = useRef(0);

  useEffect(() => {
    if (!connected) return;
    let active = true;
    const load = () => {
      const seen = edits.current;
      fetchNames().then(
        (loaded) => {
          if (!active) return;
          if (edits.current !== seen) load();
          else setList(loaded);
        },
        // 받지 못하면 이름 없이 보인다. 401이면 api가 토큰을 지워 로그인 안내가 보인다.
        () => {},
      );
    };
    load();
    return () => {
      active = false;
    };
  }, [connected, generation.value]);

  const save = async (surface: string, reading: string) => {
    const started = generation.ref.current;
    const saved = await saveName(surface, reading);
    if (generation.ref.current !== started) return;
    edits.current += 1;
    setList((current) => [
      ...current.filter((name) => name.surface !== saved.surface),
      saved,
    ]);
  };
  const remove = async (surface: string) => {
    const started = generation.ref.current;
    await removeName(surface);
    if (generation.ref.current !== started) return;
    edits.current += 1;
    setList((current) => current.filter((name) => name.surface !== surface));
  };
  const clear = useCallback(() => setList([]), []);

  const names = new Map(list.map(({ surface, reading }) => [surface, reading]));
  return { names, save, remove, clear };
}
