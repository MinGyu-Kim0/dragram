import type { PatternConnection } from "./api";
import { tokenRequest } from "./token-request";

// 문장이나 원문 구간 없이 공용 패턴 ID만 보낸다. 서버는 저장된 값을 쓰거나 없는 것만 채운다.
export async function fetchConnection(
  patternId: number,
): Promise<PatternConnection> {
  const response = await tokenRequest(
    `/api/grammar-patterns/${patternId}/connection/`,
    "POST",
  );
  const result = (await response.json()) as
    PatternConnection | { error: string };
  if ("error" in result) throw new Error("접속 형태 생성 실패");
  return result;
}
