import Policy20261028 from "./privacy/Policy20261028";
import VersionedDocument from "./VersionedDocument";

const POLICIES = [{ effective: "2026-10-28", Body: Policy20261028 }];

function PrivacyPage() {
  return (
    <VersionedDocument
      title="개인정보처리방침"
      path="privacy"
      versions={POLICIES}
      changeTitle="15. 처리방침이 바뀌면 어떻게 알리나요?"
      changeNote={
        <>
          <p>
            최신 처리방침은 웹사이트의 개인정보처리방침 메뉴에서 로그인하지 않고
            볼 수 있도록 공개합니다. 이전 버전도 시행일과 함께 보관해 아래에서
            확인할 수 있도록 합니다.
          </p>
          <p>
            문구나 연락처만 바뀌면 변경된 방침과 변경일을 게시합니다. 보유기간,
            처리업체, 이전 국가처럼 권리에 영향을 주는 변경은 시행 전에 주요
            내용과 변경 전·후 비교를 안내합니다. 필요한 경우 가입 이메일로도
            안내합니다. 새로운 처리 목적이나 항목을 추가할 때에는 시행 전에
            동의나 다른 적법한 근거가 필요한지 확인하고 필요한 절차를 거칩니다.
          </p>
        </>
      }
    />
  );
}

export default PrivacyPage;
