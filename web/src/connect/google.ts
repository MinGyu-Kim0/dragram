// Google Identity Services 로그인 버튼. 클라이언트 ID(공개 값)만 쓰고 비밀값은 쓰지 않는다.

type CredentialResponse = { credential: string };

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(config: {
            client_id: string;
            callback: (response: CredentialResponse) => void;
          }): void;
          renderButton(
            parent: HTMLElement,
            options: Record<string, string>,
          ): void;
        };
      };
    };
  }
}

const SCRIPT_URL = "https://accounts.google.com/gsi/client";
let loading: Promise<void> | undefined;

function loadScript() {
  if (window.google?.accounts) return Promise.resolve();
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      loading = undefined;
      reject(new Error("Google 로그인 스크립트를 불러오지 못함"));
    };
    document.head.append(script);
  });
  return loading;
}

/** parent에 'Google 계정으로 계속하기' 버튼을 그린다. 로그인하면 ID 토큰을 넘긴다. */
export async function renderGoogleButton(
  parent: HTMLElement,
  onCredential: (credential: string) => void,
) {
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
  if (!clientId) throw new Error("VITE_GOOGLE_CLIENT_ID가 없음");
  await loadScript();
  const id = window.google!.accounts.id;
  id.initialize({
    client_id: clientId,
    callback: (r) => onCredential(r.credential),
  });
  id.renderButton(parent, {
    theme: "outline",
    size: "large",
    text: "continue_with",
    shape: "pill",
  });
}
