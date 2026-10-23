/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Google OAuth 클라이언트 ID(공개 값). 비밀값은 웹에 두지 않는다. */
  readonly VITE_GOOGLE_CLIENT_ID?: string;
  /** 연결 메시지를 보낼 확장 프로그램 ID. 개발용은 manifest key로 고정한 ID다. */
  readonly VITE_EXTENSION_ID?: string;
}
