import Policy20261029 from "./privacy/Policy20261029";
import Policy20261101 from "./privacy/Policy20261101";
import Terms20261029 from "./terms/Terms20261029";
import Terms20261101 from "./terms/Terms20261101";
import type { Version } from "./VersionedDocument";

// 처리방침·약관의 시행일별 판. 맨 앞이 최신본이고, 가입 화면도 이 최신본을 보여 준다.
// 개정하면 backend accounts/views.py의 PRIVACY_VERSION·TERMS_VERSION도 함께 바꾼다.
export const POLICIES: Version[] = [
  { effective: "2026-11-01", Body: Policy20261101 },
  { effective: "2026-10-29", Body: Policy20261029 },
];

// 시행일은 처리방침과 같은 날로 맞춘다(#249).
export const TERMS: Version[] = [
  { effective: "2026-11-01", Body: Terms20261101 },
  { effective: "2026-10-29", Body: Terms20261029 },
];
