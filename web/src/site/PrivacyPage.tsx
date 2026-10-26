import SiteLayout, { ContactEmail, Section } from "./SiteLayout";

// 개인정보처리방침(DESIGN WebPolicy): 수집 정보 → 공용·개인 데이터 → 처리 위탁(OpenAI) → 보관 기간
// → 삭제 요청. 내용은 지금 구현이 실제로 저장·전송하는 것과 맞춘다.

function PrivacyPage() {
  const officer = import.meta.env.VITE_PRIVACY_OFFICER;
  return (
    <SiteLayout>
      <article className="document">
        <h1>개인정보처리방침</h1>
        <p className="muted">시행일: 2026년 10월 27일</p>

        <Section title="수집하는 정보">
          <ul>
            <li>Google 로그인 정보: 이메일 주소와 Google 계정 식별자</li>
            <li>
              분석을 요청한 일본어 문장(드래그한 부분을 넓힌 문장)과 분석한 시각
            </li>
            <li>직접 지정한 이름과 그 읽기</li>
            <li>
              사용 기록: 요청 시각, AI 사용량(토큰 수). 문장 원문은 담지 않아요.
            </li>
            <li>
              확장 프로그램 연결 정보: 연결 토큰은 원본 대신 해시만 저장해요.
            </li>
            <li>
              접속 기록: 서버 로그에 IP 주소, 요청 경로, 시각이 남을 수 있어요.
              문장 원문은 남기지 않아요.
            </li>
          </ul>
          <p>문장을 가져온 웹페이지 주소는 받지도 저장하지도 않아요.</p>
        </Section>

        <Section title="공용 데이터와 개인 데이터">
          <p>
            분석한 문장의 원문, 지정한 이름은 개인 데이터로 저장되고 본인만 볼
            수 있어요. 관리자 화면에도 원문은 보이지 않아요.
          </p>
          <p>
            같은 문장을 다시 분석하지 않도록 분석 결과는 모든 사용자가 함께
            써요. 이 공용 데이터에는 원문 대신 문장 해시, 문법·단어 구간의
            위치와 식별자, 한국어 번역만 저장해요. 번역은 문장 전체를 옮긴
            글이라, 같은 문장을 분석한 다른 사용자에게도 보여요.
          </p>
        </Section>

        <Section title="처리 위탁">
          <p>
            번역과 문법·단어 판정을 위해 분석할 문장(숫자는 자리표시자로 바꿈)과
            형태소 정보를 OpenAI(미국)에 보내요. OpenAI는 API로 받은 내용을 모델
            학습에 쓰지 않으며, 악용 감시를 위해 최대 30일 보관한 뒤 지워요.
          </p>
          <ul>
            <li>OpenAI, L.L.C.(미국): 번역과 문법·단어 판정</li>
            <li>Amazon Web Services(서울 리전): 서버와 데이터베이스 운영</li>
            <li>Google LLC: 로그인 인증</li>
          </ul>
        </Section>

        <Section title="보관 기간">
          <ul>
            <li>
              계정 정보, 분석한 문장 원문, 지정한 이름: 삭제를 요청할 때까지
            </li>
            <li>분석 작업에 넣은 문장: 분석이 끝나면 바로 지워요.</li>
            <li>
              사용 기록: 원문 없이 보관하고, 계정을 지우면 계정과의 연결을 끊어
              누구의 기록인지 알 수 없게 해요.
            </li>
            <li>공용 분석 결과: 원문 없이 계속 보관해요.</li>
          </ul>
        </Section>

        <Section title="삭제 요청">
          <p>
            분석 기록이나 계정 삭제는 <ContactEmail />로 요청해 주세요. 가입한
            Google 계정 메일로 보내 주시면 본인인지 확인한 뒤, 요청을 받은
            날부터 10일 안에 계정 정보, 분석한 문장 원문, 지정한 이름, 연결
            토큰을 지워요.
          </p>
        </Section>

        <Section title="개인정보 보호책임자">
          <p>
            {officer || "보호책임자 준비 중"} · <ContactEmail />
          </p>
        </Section>
      </article>
    </SiteLayout>
  );
}

export default PrivacyPage;
