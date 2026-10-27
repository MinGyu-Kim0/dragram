import SiteLayout, {
  CC_BY_SA_URL,
  ContactEmail,
  JMDICT_URL,
  Section,
} from "./SiteLayout";

function TermsPage() {
  return (
    <SiteLayout>
      <article className="document">
        <h1>이용약관</h1>
        <p className="muted">시행일: 2026년 10월 27일</p>

        <Section title="서비스 범위">
          <p>
            Dragram은 사용자가 고른 일본어 문장을 분석해 번역과 문법·단어 정보를
            보여주는 학습 도구예요. Chrome 확장 프로그램과 이 웹사이트로
            제공하고, 확장 프로그램에서 분석하려면 Google 계정으로 로그인해야
            해요.
          </p>
        </Section>

        <Section title="AI가 만든 내용의 한계">
          <p>
            번역과 문법·단어 설명의 일부는 AI가 만들어요. 관리자가 아직 확인하지
            않은 내용에는 'AI 생성·미검수' 배지가 붙고, 틀릴 수 있어요. 학습
            참고용으로 쓰고, 정확성이 중요한 곳에는 다른 자료로 확인해 주세요.
          </p>
        </Section>

        <Section title="단어 정보의 출처">
          <p>
            단어 정보는 <a href={JMDICT_URL}>JMdict</a>(Electronic Dictionary
            Research and Development Group, EDRDG)를 바탕으로 하며,{" "}
            <a href={CC_BY_SA_URL}>CC BY-SA 4.0</a> 라이선스를 따라요. 이
            라이선스에 따라 누구나 이 단어 정보를 출처를 밝히고 같은 라이선스로
            다시 배포할 수 있고, Dragram은 이를 막지 않아요.
          </p>
        </Section>

        <Section title="이용자의 책임">
          <ul>
            <li>다른 사람의 계정이나 연결 토큰을 쓰지 않아요.</li>
            <li>
              서비스를 자동화된 방법으로 대량 호출하거나 운영을 방해하지 않아요.
            </li>
          </ul>
        </Section>

        <Section title="서비스 변경과 중단">
          <p>
            서비스는 기능을 바꾸거나 일시 중단할 수 있어요. 약관이 바뀌면 이
            페이지에 시행일과 함께 알려요.
          </p>
        </Section>

        <Section title="문의">
          <p>
            <ContactEmail />
          </p>
        </Section>
      </article>
    </SiteLayout>
  );
}

export default TermsPage;
