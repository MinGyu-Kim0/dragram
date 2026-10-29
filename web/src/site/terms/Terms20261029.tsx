import { Link } from "react-router";
import { Unconfirmed } from "../privacy/Unconfirmed";
import { CC_BY_SA_URL, ContactEmail, JMDICT_URL, Section } from "../SiteLayout";

// #249에서 정한 약관 1~15절. 처리방침과 같은 합니다체로 쓴다. 시행한 뒤에는 고치지 않고 새
// 시행일 파일을 만든다.

function Terms20261029() {
  const officer = import.meta.env.VITE_PRIVACY_OFFICER;
  const name = officer || <Unconfirmed what="운영자 이름" />;
  return (
    <>
      <Section title="운영자와 적용 범위">
        <p>
          Dragram은 개인 개발자 {name}이(가) 운영합니다. 이 약관은 Dragram
          웹사이트와 Chrome 확장 프로그램에 적용됩니다.
        </p>
        <p>
          연락 메일: <ContactEmail />
        </p>
      </Section>

      <Section title="서비스 범위">
        <p>
          Dragram은 사용자가 고른 일본어 문장을 분석해 번역과 문법·단어 정보를
          보여주는 학습 도구입니다. Chrome 확장 프로그램과 이 웹사이트로
          제공하며, 확장 프로그램에서 분석하려면 Google 계정으로 로그인해야
          합니다. 현재는 무료로 제공합니다.
        </p>
      </Section>

      <Section title="계정">
        <p>
          만 14세 이상만 가입할 수 있습니다. Google 계정으로 로그인하면
          가입되며, 가입할 때 이 약관에 동의하는 것으로 만 14세 이상임을
          확인합니다. 나중에 14세 미만임을 알게 되면 계정과 기록을 삭제합니다.
          웹사이트의 연결 화면에서 직접 탈퇴할 수 있고, 탈퇴하면 내 기록이
          삭제됩니다. 무엇이 언제 삭제되는지는{" "}
          <Link to="/privacy">개인정보처리방침</Link>에서 안내합니다.
        </p>
      </Section>

      <Section title="사용량 한도">
        <p>
          하루에 쓸 수 있는 사용량과 한 번에 보낼 수 있는 요청 수에 한도가
          있습니다. 한도를 넘으면 분석 요청이 거부됩니다. 한도 값은 운영 상황에
          따라 바뀔 수 있습니다. 탈퇴한 뒤 같은 날 다시 가입해도 그날 한도는
          이어집니다.
        </p>
      </Section>

      <Section title="AI가 만든 내용의 한계">
        <p>
          번역과 문법·단어 설명의 일부는 AI가 만듭니다. 관리자가 아직 확인하지
          않은 내용에는 'AI 생성·미검수' 배지가 붙으며, 틀릴 수 있습니다. 학습
          참고용으로 쓰고, 정확성이 중요한 곳에는 다른 자료로 확인해 주세요.
        </p>
      </Section>

      <Section title="입력한 글과 공용 분석">
        <p>
          분석하는 글의 저작권은 원래 저작자에게 있습니다. 자신이 읽을 권리가
          있는 글을 분석해 주세요.
        </p>
        <p>
          Dragram은 문장 원문은 공용으로 저장하지 않습니다. 원문은 분석한 사람의
          학습 기록에만 남고 본인만 볼 수 있습니다. 다만 같은 문장을 매번 새로
          분석하지 않도록, 번역과 분석 결과는 같은 문장을 분석한 사용자끼리 함께
          씁니다.
        </p>
      </Section>

      <Section title="권리 침해와 개인정보 신고">
        <p>
          저작권자는 연락 메일로 해당 문장을 알려 그 문장의 공용 분석을 삭제해
          달라고 요청할 수 있습니다. 공용 번역·분석에 본인이나 다른 사람의
          개인정보가 들어 있으면 누구나 같은 메일로 삭제나 재사용 중단을 요청할
          수 있습니다. 확인한 뒤 삭제하고 결과를 알려 드립니다.
        </p>
      </Section>

      <Section title="단어 정보의 출처">
        <p>
          단어 정보는 <a href={JMDICT_URL}>JMdict</a>(Electronic Dictionary
          Research and Development Group, EDRDG)를 바탕으로 하며,{" "}
          <a href={CC_BY_SA_URL}>CC BY-SA 4.0</a> 라이선스를 따릅니다. 이
          라이선스에 따라 누구나 이 단어 정보를 출처를 밝히고 같은 라이선스로
          다시 배포할 수 있으며, Dragram은 이를 막지 않습니다.
        </p>
      </Section>

      <Section title="이용자가 하지 않을 일">
        <ul>
          <li>
            자동화된 방법으로 대량 호출하거나, 탈퇴·재가입을 되풀이하는 등
            사용량 한도를 피해 가지 않습니다.
          </li>
          <li>다른 사람의 계정이나 연결 토큰을 쓰지 않습니다.</li>
          <li>
            서비스를 공격하거나, 인증을 우회하거나, 운영을 방해하지 않습니다.
          </li>
          <li>
            불법 콘텐츠나 다른 사람의 개인정보가 든 글을 되풀이해 넣지 않습니다.
            민감한 내용은 분석하지 말아 주세요.
          </li>
        </ul>
      </Section>

      <Section title="이용 제한과 이의 제기">
        <p>
          위의 행위를 하면 정도에 따라 경고하거나 계정을 정지합니다. 대량
          호출이나 공격처럼 비용·보안에 급한 경우에는 경고 없이 바로 정지할 수
          있습니다. 경고와 정지 사실은 가입한 이메일로 알려 드립니다.
        </p>
        <p>
          정지에 이의가 있으면 연락 메일로 알려 주세요. 확인해서 잘못된
          정지였으면 해제합니다. 정지된 상태에서도 연락 메일로 탈퇴를 요청할 수
          있습니다(로그인이 되지 않아 화면에서는 탈퇴할 수 없습니다).
        </p>
      </Section>

      <Section title="서비스 변경과 중단">
        <p>서비스는 기능을 바꾸거나 일시 중단할 수 있습니다.</p>
      </Section>

      <Section title="책임 범위">
        <p>
          Dragram은 무료 서비스이며 AI가 만든 결과에는 오류가 있을 수 있습니다.
          따라서 서비스나 그 결과를 이용해 생긴 손해에 대한 운영자의 책임은
          제한됩니다. 다만 운영자의 고의나 중대한 과실로 생긴 손해는 운영자가
          책임집니다.
        </p>
      </Section>

      <Section title="약관 변경">
        <p>
          약관을 바꾸면 시행 7일 전에 이 웹사이트에 알립니다. 이용자에게 불리한
          변경은 시행 30일 전에 알리고, 가입한 이메일로도 알려 드립니다. 이전
          버전은 이 페이지 아래의 버전별 주소에서 볼 수 있습니다.
        </p>
      </Section>

      <Section title="준거법">
        <p>이 약관은 대한민국 법을 따릅니다.</p>
      </Section>

      <Section title="개인정보와 문의">
        <p>
          개인정보는 <Link to="/privacy">개인정보처리방침</Link>을 따릅니다.
        </p>
        <p>
          문의: <ContactEmail />
        </p>
      </Section>
    </>
  );
}

export default Terms20261029;
