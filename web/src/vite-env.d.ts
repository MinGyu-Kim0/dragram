/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Google OAuth 클라이언트 ID(공개 값). 비밀값은 웹에 두지 않는다. */
  readonly VITE_GOOGLE_CLIENT_ID?: string;
}
