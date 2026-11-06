import { useEffect, useState } from "react";
import { watchUpdateRequired } from "@/utils/api";

// 서버가 이 확장 버전을 거부했다(#349). 업데이트하면 확장이 다시 뜨므로 되돌리지 않는다.
export function useUpdateRequired() {
  const [required, setRequired] = useState(false);
  useEffect(() => watchUpdateRequired(() => setRequired(true)), []);
  return required;
}
