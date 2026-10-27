import Terms20261028 from "./terms/Terms20261028";
import VersionedDocument from "./VersionedDocument";

// 시행일은 처리방침과 같은 날로 맞춘다(#249).
const TERMS = [{ effective: "2026-10-28", Body: Terms20261028 }];

function TermsPage() {
  return (
    <VersionedDocument
      title="이용약관"
      path="terms"
      versions={TERMS}
      changeTitle="이전 버전"
    />
  );
}

export default TermsPage;
