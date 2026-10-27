import { ContactEmail, Section } from "../SiteLayout";
import { Unconfirmed } from "./Unconfirmed";

// #237에서 정한 처리방침 1~12절. 시행한 뒤에는 고치지 않고 새 시행일 파일을 만든다.

const OPENAI_DATA_POLICY_URL =
  "https://platform.openai.com/docs/guides/your-data";

function Policy20261028() {
  const officer = import.meta.env.VITE_PRIVACY_OFFICER;
  const name = officer || <Unconfirmed what="운영자 이름" />;
  return (
    <>
      <Section title="운영주체와 시행일">
        <p>
          Dragram은 개인 개발자 {name}이(가) 운영해요. 이 방침은 Dragram
          웹사이트와 Chrome 확장 프로그램에 적용돼요.
        </p>
        <p>
          문의: <ContactEmail />
        </p>
      </Section>

      <Section title="처리하는 정보와 목적">
        <p>
          Dragram은 서비스를 제공하는 데 꼭 필요한 정보만 처리해요. 동의를 따로
          받아야 하는 처리(광고, 마케팅 등)는 하지 않아요.
        </p>
        <ul>
          <li>
            <strong>Google 로그인</strong>: Google 계정 식별자와 이메일 주소를
            받아요. 계정을 확인해 로그인시키고, 문의에 답하고, 이 방침이 바뀌면
            알리는 데 써요. Google 비밀번호는 받지 않고, Gmail이나 Drive 같은
            다른 권한도 요청하지 않아요.
          </li>
          <li>
            <strong>로그인 유지</strong>: 웹사이트는 로그인 상태를 유지하는 세션
            쿠키와 위조 요청을 막는 CSRF 쿠키를 써요. 확장 프로그램은 계정을
            연결할 때 받은 연결 토큰을 확장 안에 저장하고, 서버에는 토큰 원본
            대신 해시만 저장해요. 광고나 방문 분석용 쿠키는 쓰지 않아요.
          </li>
          <li>
            <strong>분석한 문장</strong>: 'Dragram으로 분석'을 누르면 드래그한
            부분을 포함한 문장 전체를 서버로 보내요. 분석 결과가 저장되면 그
            문장의 원문, 원문 해시, 분석 결과와의 연결, 문장 속 이름의 한글
            읽기, 분석한 시각이 내 학습 기록으로 저장돼요. 따로 저장 버튼을
            누르지 않아도 저장돼요. 문장을 가져온 웹페이지의 주소와 제목은
            보내지 않아요.
          </li>
          <li>
            <strong>지정한 이름</strong>: 내가 직접 지정한 이름의 표기와 읽기를
            저장해요.
          </li>
          <li>
            <strong>사용량 기록</strong>: 처리 방법, 사용한 AI 모델, 토큰 수,
            성공 여부, 시각을 남겨요. 하루 사용량 한도와 비용을 확인하는 데
            써요. 문장 원문은 담지 않아요.
          </li>
          <li>
            <strong>접속 기록</strong>: 서버에 IP 주소, 요청한 주소, 시각이
            남아요. 장애와 보안 문제를 살피는 데 써요.
          </li>
          <li>
            <strong>확장 프로그램 안에만 저장하는 것</strong>: 루비 표시 같은
            화면 설정, 연결한 계정 번호, 연결 토큰, 분석 요청을 사이드 패널에
            넘기는 임시 기록(읽으면 바로 지워요). 이 값들은 서버로 보내지 않고,
            확장 프로그램을 지우면 함께 지워져요.
          </li>
        </ul>
      </Section>

      <Section title="공용 분석과 내 기록">
        <p>
          내 학습 기록(문장 원문)과 지정한 이름은 본인만 볼 수 있어요. 다른
          사용자에게는 보이지 않아요.
        </p>
        <p>
          같은 문장을 매번 새로 분석하지 않도록, 분석 결과는 여러 사용자가 함께
          써요. 이 공용 분석에는 원문 대신 문장 해시, 문법·단어가 문장의 몇 번째
          글자에 있는지, 뜻 번호, 한국어 번역만 저장해요. 인터넷에 공개한다는
          뜻은 아니에요. 다만 번역은 문장 전체를 옮긴 글이라, 같은 문장을 분석한
          다른 사용자에게도 보여요.
        </p>
        <p>
          내 기록에서 문장을 지워도 공용 분석은 남아요. 대신 그 분석과 내 계정의
          연결은 끊어져요.
        </p>
      </Section>

      <Section title="처리위탁과 국외이전">
        <p>
          번역과 문법·단어 판정을 위해 분석할 문장(숫자는 자리표시자로 바꾼
          형태)과 형태소·문법·단어 후보를 OpenAI에 보내요. 문장 속 이름이나
          문맥은 그대로 갈 수 있어요. 계정 이메일은 보내지 않아요.
        </p>
        <table>
          <tbody>
            <tr>
              <th scope="row">받는 자와 연락처</th>
              <td>
                <Unconfirmed what="OpenAI 계약 법인" /> (
                <Unconfirmed what="OpenAI 개인정보 문의 연락처" />)
              </td>
            </tr>
            <tr>
              <th scope="row">이전되는 국가</th>
              <td>
                <Unconfirmed what="OpenAI 처리 국가" />
              </td>
            </tr>
            <tr>
              <th scope="row">이전되는 항목</th>
              <td>
                분석할 문장(숫자는 자리표시자로 바꾼 형태), 형태소·문법·단어
                후보
              </td>
            </tr>
            <tr>
              <th scope="row">시기와 방법</th>
              <td>분석을 요청할 때마다 암호화된 연결(HTTPS)로 보내요.</td>
            </tr>
            <tr>
              <th scope="row">목적</th>
              <td>번역과 문법·단어 판정</td>
            </tr>
            <tr>
              <th scope="row">보유기간</th>
              <td>
                응답을 저장하지 않도록 요청해요. OpenAI는 악용을 막기 위해
                요청을 최대 30일 동안 보관할 수 있어요(
                <a href={OPENAI_DATA_POLICY_URL}>OpenAI API 데이터 정책</a>). AI
                모델 학습에 쓰이는지:{" "}
                <Unconfirmed what="OpenAI 데이터 공유 설정" />
              </td>
            </tr>
            <tr>
              <th scope="row">거부 방법과 효과</th>
              <td>
                분석을 누르지 않으면 아무것도 보내지 않아요. 보내기를 원하지
                않으면 문장 분석을 쓸 수 없어요.
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          서버와 데이터베이스는 Amazon Web Services(AWS Lightsail, 서울 리전)에
          맡겨 운영해요.
        </p>
      </Section>

      <Section title="보유기간">
        <ul>
          <li>계정 정보(Google 계정 식별자, 이메일): 탈퇴할 때까지</li>
          <li>
            내 학습 기록(문장 원문)과 지정한 이름: 내가 지우거나 탈퇴할 때까지.
            기간 제한은 없어요.
          </li>
          <li>
            확장 프로그램 연결 토큰: 마지막으로 쓴 뒤 90일이 지나면 더는 쓸 수
            없고, 탈퇴하면 지워요.
          </li>
          <li>사용량 기록: 탈퇴하면 지워요.</li>
          <li>분석 작업에 넣은 문장: 분석이 끝나면 바로 지워요.</li>
          <li>공용 분석: 원문 없이 계속 보관해요.</li>
          <li>
            서버 접속 기록: <Unconfirmed what="서버 접속 기록 보관 기간" />
          </li>
          <li>
            백업: 지운 정보도 백업에는{" "}
            <Unconfirmed what="서버 스냅샷·DB 백업 보관 기간" /> 동안 남았다가
            지워져요.
          </li>
        </ul>
      </Section>

      <Section title="삭제와 탈퇴">
        <ul>
          <li>
            <strong>문장 삭제</strong>: 내 기록에서 문장을 지우면 그 원문이
            지워지고, 공용 분석과 내 계정의 연결도 끊어져요.
          </li>
          <li>
            <strong>지정한 이름 삭제</strong>: 지운 이름은 다음 분석부터 쓰지
            않아요.
          </li>
          <li>
            <strong>회원 탈퇴</strong>: 웹사이트의 연결 화면에서 직접 탈퇴할 수
            있어요. 탈퇴하면 계정 정보, 학습 기록, 지정한 이름, 확장 프로그램
            연결, 사용량 기록이 모두 지워지고, 연결된 확장 프로그램도 더는 내
            계정으로 분석하지 않아요. 같은 Google 계정으로 다시 로그인하면 빈 새
            계정으로 시작해요.
          </li>
        </ul>
        <p>
          확장 프로그램을 지워도 서버의 기록은 지워지지 않아요. Google 계정에서
          Dragram 연결을 해제해도 마찬가지예요. 서버의 기록을 지우려면 탈퇴해
          주세요. 지운 정보는 백업에{" "}
          <Unconfirmed what="서버 스냅샷·DB 백업 보관 기간" /> 동안 남을 수
          있어요.
        </p>
      </Section>

      <Section title="권리행사">
        <p>
          내 정보를 보거나, 고치거나, 지우거나, 처리를 멈춰 달라고 요청할 수
          있어요. 화면에 있는 기능을 쓰거나 <ContactEmail />로 요청해 주세요.
          가입한 Google 계정의 이메일로 보낸 요청인지로 본인인지 확인하고,
          요청을 받은 날부터 10일 안에 처리해요.
        </p>
      </Section>

      <Section title="운영자가 원문을 보는 경우">
        <p>
          내 원문은 본인만 조회할 수 있고, 관리 화면에도 원문을 보여 주지
          않아요. 다만 서버에 저장하는 이상 운영자가 원문을 볼 수 있는 방법이
          아예 없는 것은 아니에요. 운영자가 원문을 읽는 경우는 다음으로
          한정해요.
        </p>
        <ul>
          <li>내가 특정 기록을 봐도 된다고 한 문의를 처리할 때</li>
          <li>보안 사고를 조사할 때</li>
          <li>법에 따라 꼭 해야 할 때</li>
        </ul>
      </Section>

      <Section title="어린이 이용자">
        <p>
          Dragram은 나이 제한이 없어요. 그래서 보호자 동의가 필요한 처리는 하지
          않고, 서비스에 꼭 필요한 처리만 해요. 이 방침도 누구나 읽을 수 있도록
          쉬운 말로 썼어요.
        </p>
      </Section>

      <Section title="민감한 내용은 분석하지 마세요">
        <p>
          다른 사람의 개인정보나 건강, 사생활 같은 민감한 내용이 든 문장은
          분석하지 마세요. 분석한 원문이나 AI가 만든 결과에 개인정보가 들어간
          것을 알게 되면 <ContactEmail />로 알려 주세요. 확인한 뒤 지워요.
        </p>
      </Section>

      <Section title="개인정보 보호책임자와 도움받을 곳">
        <p>
          개인정보 보호책임자: {name} · <ContactEmail />
        </p>
        <p>개인정보 침해로 도움이 필요하면 아래 기관에도 문의할 수 있어요.</p>
        <ul>
          <li>
            개인정보침해 신고센터:{" "}
            <a href="https://privacy.kisa.or.kr">privacy.kisa.or.kr</a>, 국번
            없이 118
          </li>
          <li>
            개인정보 분쟁조정위원회:{" "}
            <a href="https://www.kopico.go.kr">www.kopico.go.kr</a>, 1833-6972
          </li>
          <li>
            대검찰청: <a href="https://www.spo.go.kr">www.spo.go.kr</a>, 국번
            없이 1301
          </li>
          <li>
            경찰청: <a href="https://ecrm.police.go.kr">ecrm.police.go.kr</a>,
            국번 없이 182
          </li>
        </ul>
      </Section>
    </>
  );
}

export default Policy20261028;
