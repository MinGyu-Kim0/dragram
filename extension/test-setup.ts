import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest globals를 켜지 않아 Testing Library가 자동 정리를 등록하지 못하므로 직접 등록한다.
afterEach(cleanup);

// 테스트는 서버를 부르지 않는다. 테스트가 끝난 뒤 늦게 부른 fetch는 vi.unstubAllGlobals가 되돌린
// 원래 fetch로 나가, 로컬 백엔드의 401이 다음 테스트가 저장한 같은 토큰을 지웠다. stubGlobal이
// 아니라 직접 바꿔, 되돌려도 이 가짜가 남게 한다.
globalThis.fetch = () =>
  Promise.reject(new TypeError("테스트에서 진짜 fetch를 불렀습니다"));
