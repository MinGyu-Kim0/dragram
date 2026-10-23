import { useCallback, useEffect, useRef, useState } from "react";
import { currentUser, loginWithGoogle, logout, type User } from "./auth";
import { renderGoogleButton } from "./google";
import "./connect.css";

// 로그인·확장 연결 화면(DESIGN WebConnect)의 로그인 카드. 연결 성공 카드는 #109에서 만든다.

type State =
  | { kind: "loading" }
  | { kind: "signedOut"; failed: boolean }
  | { kind: "signedIn"; user: User };

function GoogleButton({
  onCredential,
  onError,
}: {
  onCredential: (credential: string) => void;
  onError: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    renderGoogleButton(ref.current!, onCredential).catch(onError);
  }, [onCredential, onError]);
  return <div ref={ref} className="google-button" />;
}

function ConnectPage() {
  const [state, setState] = useState<State>({ kind: "loading" });
  // Google 버튼을 그리지 못함(클라이언트 ID 없음, 스크립트를 못 불러옴). 로그인 실패와 따로 안내한다.
  const [buttonUnavailable, setButtonUnavailable] = useState(false);
  const buttonFailed = useCallback(() => setButtonUnavailable(true), []);

  const show = useCallback(
    (user: User | null) =>
      setState(
        user
          ? { kind: "signedIn", user }
          : { kind: "signedOut", failed: false },
      ),
    [],
  );
  const fail = useCallback(
    () => setState({ kind: "signedOut", failed: true }),
    [],
  );
  // Google 버튼은 이 함수가 바뀔 때마다 다시 그리므로 한 번만 만든다.
  const login = useCallback(
    (credential: string) => loginWithGoogle(credential).then(show, fail),
    [show, fail],
  );

  useEffect(() => {
    currentUser().then(show, fail);
  }, [show, fail]);

  return (
    <main className="connect">
      <section className="card">
        {state.kind === "loading" && <p className="muted">확인하는 중…</p>}
        {state.kind === "signedOut" && (
          <>
            <h1>Dragram에 로그인</h1>
            <p className="secondary">
              Google 계정으로 로그인하면 확장 프로그램에 계정을 연결할 수
              있어요.
            </p>
            {state.failed && (
              <p role="alert" className="danger">
                로그인하지 못했어요. 다시 시도해 주세요.
              </p>
            )}
            {buttonUnavailable && (
              <p role="alert" className="danger">
                로그인 버튼을 불러오지 못했어요. 잠시 뒤 다시 열어 주세요.
              </p>
            )}
            <GoogleButton onCredential={login} onError={buttonFailed} />
            <p className="muted">
              로그인하면 Google 계정의 이메일과 계정 식별자만 받아요.
            </p>
          </>
        )}
        {state.kind === "signedIn" && (
          <>
            <h1>로그인했어요</h1>
            <p className="secondary">
              <strong>{state.user.email}</strong> 계정으로 로그인했어요.
            </p>
            <button
              type="button"
              className="secondary-button"
              onClick={() => logout().then(show, fail)}
            >
              로그아웃
            </button>
          </>
        )}
      </section>
    </main>
  );
}

export default ConnectPage;
