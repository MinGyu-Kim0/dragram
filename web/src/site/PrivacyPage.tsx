import Policy20261028 from "./privacy/Policy20261028";
import VersionedDocument from "./VersionedDocument";

const POLICIES = [{ effective: "2026-10-28", Body: Policy20261028 }];

function PrivacyPage() {
  return (
    <VersionedDocument
      title="개인정보처리방침"
      path="privacy"
      versions={POLICIES}
      changeTitle="변경 안내와 이전 버전"
      changeNote={
        <p>
          문구나 연락처만 바뀌면 바로 새 버전을 올려요. 보유기간, 맡기는 업체,
          정보가 가는 나라가 바뀌면 시행하기 전에 미리 알리고 무엇이 바뀌는지
          비교표로 보여 드려요. 새로운 정보를 받거나 새로운 목적으로 쓰게 되면
          시행하기 전에 그 근거를 다시 갖춰요.
        </p>
      }
    />
  );
}

export default PrivacyPage;
