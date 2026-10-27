import { useCallback, useEffect, useRef, useState } from "react";
import {
  currentUser,
  issueExtensionToken,
  loginWithGoogle,
  logout,
  withdraw,
  type User,
} from "./auth";
import { sendToExtension } from "./extension";
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
              로그인하면 Google 계정의 이메일과 계정 식별자만 저장해요.
            </p>
          </>
        )}
        {state.kind === "signedIn" && (
          <SignedIn user={state.user} onLoggedOut={() => show(null)} />
        )}
      </section>
    </main>
  );
}

type Problem =
  "logoutFailed" | "withdrawFailed" | "extensionMissing" | "connectFailed";

const PROBLEMS: Record<Problem, string> = {
  logoutFailed: "로그아웃하지 못했어요. 다시 시도해 주세요.",
  withdrawFailed: "탈퇴하지 못했어요. 다시 시도해 주세요.",
  extensionMissing:
    "확장 프로그램을 찾지 못했어요. 설치하고 켜 둔 뒤 다시 눌러 주세요.",
  connectFailed: "연결하지 못했어요. 다시 시도해 주세요.",
};

// 로그인 카드(로그인 뒤) → 확장 연결 → 연결 성공 카드
// 연결(발급·전달)과 로그아웃은 같은 출처의 모든 탭에서 한 번에 하나만 한다. 다른 탭의 로그아웃이
// 폐기한 토큰을 늦게 끝난 연결이 확장에 넘기지 않게 한다. Web Locks가 없으면 그냥 실행한다.
function oneAtATime(task: () => Promise<void>) {
  const locks = globalThis.navigator?.locks;
  return locks ? locks.request("dragram-connect", task) : task();
}

function SignedIn({
  user,
  onLoggedOut,
}: {
  user: User;
  onLoggedOut: () => void;
}) {
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();
  const [confirmingWithdrawal, setConfirmingWithdrawal] = useState(false);

  const connect = () =>
    oneAtATime(async () => {
      setBusy(true);
      setProblem(undefined);
      try {
        const { token, account } = await issueExtensionToken();
        if (await sendToExtension({ type: "connect", token, account }))
          setConnected(true);
        else setProblem("extensionMissing");
      } catch {
        setProblem("connectFailed");
      } finally {
        setBusy(false);
      }
    });

  const signOut = () =>
    oneAtATime(async () => {
      setBusy(true);
      setProblem(undefined);
      try {
        await logout();
      } catch {
        // 실패하면 세션이 남아 있으므로 로그인한 상태를 그대로 보인다.
        setProblem("logoutFailed");
        setBusy(false);
        return;
      }
      // 서버가 이 세션의 토큰을 폐기했다. 확장이 바로 로그인 안내로 바뀌게 알린다(없어도 된다).
      await sendToExtension({ type: "disconnect" });
      onLoggedOut();
    });

  const leave = () =>
    oneAtATime(async () => {
      setBusy(true);
      setProblem(undefined);
      try {
        await withdraw();
      } catch {
        // 실패하면 계정이 남아 있으므로 로그인한 상태를 그대로 보인다.
        setProblem("withdrawFailed");
        setBusy(false);
        return;
      }
      // 서버가 확장 토큰도 지웠다. 확장이 바로 로그인 안내로 바뀌게 알린다(없어도 된다).
      await sendToExtension({ type: "disconnect" });
      onLoggedOut();
    });

  if (confirmingWithdrawal)
    return (
      <>
        <h1>탈퇴할까요?</h1>
        <p className="secondary">
          <strong>{user.email}</strong> 계정과 분석한 문장 기록, 지정한 이름,
          확장 프로그램 연결, 사용량 기록을 모두 지워요. 지운 기록은 되돌릴 수
          없어요. 원문 없이 여러 사용자가 함께 쓰는 문장 분석(번역·문법)은
          남아요.
        </p>
        {problem && (
          <p role="alert" className="danger">
            {PROBLEMS[problem]}
          </p>
        )}
        <button
          type="button"
          className="danger-button"
          disabled={busy}
          onClick={leave}
        >
          탈퇴하기
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={busy}
          onClick={() => {
            setProblem(undefined);
            setConfirmingWithdrawal(false);
          }}
        >
          취소
        </button>
      </>
    );

  return (
    <>
      {connected ? (
        <>
          <h1>연결했어요</h1>
          <p className="secondary">
            이제 확장 프로그램에서 문장을 분석할 수 있어요. 이 탭은 닫아도 돼요.
          </p>
        </>
      ) : (
        <>
          <h1>로그인했어요</h1>
          <p className="secondary">
            <strong>{user.email}</strong> 계정으로 로그인했어요.
          </p>
        </>
      )}
      {problem && (
        <p role="alert" className="danger">
          {PROBLEMS[problem]}
        </p>
      )}
      {!connected && (
        <button
          type="button"
          className="primary-button"
          disabled={busy}
          onClick={connect}
        >
          확장 프로그램 연결
        </button>
      )}
      {/* 연결과 로그아웃은 한 번에 하나만 한다. 로그아웃이 폐기한 토큰을 늦게 온 연결이 확장에
          넘기지 않게 한다. */}
      <button
        type="button"
        className="secondary-button"
        disabled={busy}
        onClick={signOut}
      >
        로그아웃
      </button>
      <button
        type="button"
        className="secondary-button"
        disabled={busy}
        onClick={() => {
          setProblem(undefined);
          setConfirmingWithdrawal(true);
        }}
      >
        회원 탈퇴
      </button>
    </>
  );
}

export default ConnectPage;
