import { lazy } from "react";
import Policy20261104 from "./privacy/Policy20261104";
import Terms20261102 from "./terms/Terms20261102";
import type { Version } from "./VersionedDocument";

// 처리방침·약관의 시행일별 판. 맨 앞이 최신본이고, 가입 화면도 이 최신본을 보여 준다.
// 개정하면 backend accounts/views.py의 PRIVACY_VERSION·TERMS_VERSION도 함께 바꾼다.
// 최신본만 정적으로 불러오고 옛 판은 lazy로 따로 묶는다(#422). 개정하면 밀려난 판을 lazy로 옮긴다.
export const POLICIES: Version[] = [
  { effective: "2026-11-04", Body: Policy20261104 },
  {
    effective: "2026-11-02",
    Body: lazy(() => import("./privacy/Policy20261102")),
  },
  {
    effective: "2026-10-29",
    Body: lazy(() => import("./privacy/Policy20261029")),
  },
];

// 처리방침과 함께 바뀌면 시행일을 같은 날로 맞춘다(#249). 처리방침만 바뀌면 약관은 그대로 둔다.
export const TERMS: Version[] = [
  { effective: "2026-11-02", Body: Terms20261102 },
  {
    effective: "2026-10-29",
    Body: lazy(() => import("./terms/Terms20261029")),
  },
];
