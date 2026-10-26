/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Google OAuth 클라이언트 ID(공개 값). 비밀값은 웹에 두지 않는다. */
  readonly VITE_GOOGLE_CLIENT_ID?: string;
  /** 연결 메시지를 보낼 확장 프로그램 ID. 개발용은 manifest key로 고정한 ID다. */
  readonly VITE_EXTENSION_ID?: string;
  /** 크롬 웹 스토어 등록 주소. 승인 전에는 비워 두고 홈에 '준비 중'을 보인다. */
  readonly VITE_CHROME_WEB_STORE_URL?: string;
  /** 개인정보·삭제 요청을 받는 메일. 정해지기 전에는 비워 둔다. */
  readonly VITE_CONTACT_EMAIL?: string;
  /** 개인정보 보호책임자 이름. 정해지기 전에는 비워 둔다. */
  readonly VITE_PRIVACY_OFFICER?: string;
}
