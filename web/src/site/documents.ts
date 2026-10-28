import Policy20261028 from "./privacy/Policy20261028";
import Terms20261028 from "./terms/Terms20261028";
import type { Version } from "./VersionedDocument";

// 처리방침·약관의 시행일별 판. 맨 앞이 최신본이고, 가입 화면도 이 최신본을 보여 준다.
// 개정하면 backend accounts/views.py의 PRIVACY_VERSION·TERMS_VERSION도 함께 바꾼다.
export const POLICIES: Version[] = [
  { effective: "2026-10-28", Body: Policy20261028 },
];

// 시행일은 처리방침과 같은 날로 맞춘다(#249).
export const TERMS: Version[] = [
  { effective: "2026-10-28", Body: Terms20261028 },
];
