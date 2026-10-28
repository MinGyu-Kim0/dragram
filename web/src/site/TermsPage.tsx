import { TERMS } from "./documents";
import VersionedDocument from "./VersionedDocument";

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
