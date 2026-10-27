import { Link, useParams } from "react-router";
import Policy20261028 from "./privacy/Policy20261028";
import SiteLayout, { Section } from "./SiteLayout";

// 개인정보처리방침. /privacy는 최신본, /privacy/<시행일>은 그 버전을 보여 준다.
// 개정할 때는 새 시행일 파일을 만들어 맨 앞에 넣고, 이전 파일은 고치지 않는다.
const POLICIES = [{ effective: "2026-10-28", Body: Policy20261028 }];

function koreanDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

function PrivacyPage() {
  const { version } = useParams();
  const policy = version
    ? POLICIES.find((p) => p.effective === version)
    : POLICIES[0];

  return (
    <SiteLayout>
      <article className="document">
        <h1>개인정보처리방침</h1>
        {policy ? (
          <>
            <p className="muted">시행일: {koreanDate(policy.effective)}</p>
            <policy.Body />
            <Section title="변경 안내와 이전 버전">
              <p>
                문구나 연락처만 바뀌면 바로 새 버전을 올려요. 보유기간, 맡기는
                업체, 정보가 가는 나라가 바뀌면 시행하기 전에 미리 알리고 무엇이
                바뀌는지 비교표로 보여 드려요. 새로운 정보를 받거나 새로운
                목적으로 쓰게 되면 시행하기 전에 그 근거를 다시 갖춰요.
              </p>
              <ul>
                {POLICIES.map((p) => (
                  <li key={p.effective}>
                    <Link to={`/privacy/${p.effective}`}>
                      {koreanDate(p.effective)} 시행
                    </Link>
                  </li>
                ))}
              </ul>
            </Section>
          </>
        ) : (
          <>
            <p>{version}에 시행한 처리방침은 없어요.</p>
            <Link to="/privacy">최신 개인정보처리방침 보기</Link>
          </>
        )}
      </article>
    </SiteLayout>
  );
}

export default PrivacyPage;
