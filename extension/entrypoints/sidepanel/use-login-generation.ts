import { useCallback, useRef, useState } from "react";

// 로그인 세대. 로그아웃(다른 계정으로 바꾼 연결 포함)하면 올라, 목록을 새로 받고 이전 로그인에서
// 보낸 요청의 늦은 응답은 버린다. 다른 사람의 지정한 이름이 섞이지 않게 한다(PR #167 리뷰).
export function useLoginGeneration() {
  const [value, setValue] = useState(0);
  const ref = useRef(0);
  const advance = useCallback(() => {
    ref.current += 1;
    setValue(ref.current);
  }, []);
  return { value, ref, advance };
}

export type LoginGeneration = ReturnType<typeof useLoginGeneration>;
