import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import {
  AuthError,
  currentUser,
  issueExtensionToken,
  loginWithGoogle,
  logout,
  signUp,
  withdraw,
  type Signup,
  type User,
} from "./auth";
import { koreanDate } from "../site/koreanDate";
import { POLICIES, TERMS } from "../site/documents";
import type { Version } from "../site/VersionedDocument";
import { sendToExtension } from "./extension";
import { renderGoogleButton } from "./google";
import "./connect.css";

// 로그인·확장 연결 화면(DESIGN WebConnect)의 로그인 카드. 연결 성공 카드는 #109에서 만든다.

type State =
  | { kind: "loading" }
  | {
      kind: "signedOut";
      problem?: "loginFailed" | "signupExpired" | "signupChanged";
    }
  | { kind: "signingUp"; signup: Signup }
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
      setState(user ? { kind: "signedIn", user } : { kind: "signedOut" }),
    [],
  );
  const fail = useCallback(
    () => setState({ kind: "signedOut", problem: "loginFailed" }),
    [],
  );
  // Google 버튼은 이 함수가 바뀔 때마다 다시 그리므로 한 번만 만든다.
  const login = useCallback(
    (credential: string) =>
      loginWithGoogle(credential).then(
        ({ user, signup }) =>
          signup ? setState({ kind: "signingUp", signup }) : show(user),
        fail,
      ),
    [show, fail],
  );

  useEffect(() => {
    currentUser().then(show, fail);
  }, [show, fail]);

  return (
    <main className="connect">
      {/* 가입 화면은 문서를 읽으므로 카드를 넓힌다. */}
      <section className={state.kind === "signingUp" ? "card wide" : "card"}>
        {state.kind === "loading" && <p className="muted">확인하는 중…</p>}
        {state.kind === "signedOut" && (
          <>
            <h1>Dragram에 로그인</h1>
            <p className="secondary">
              Google 계정으로 로그인하면 확장 프로그램에 계정을 연결할 수
              있어요.
            </p>
            {state.problem === "loginFailed" && (
              <p role="alert" className="danger">
                로그인하지 못했어요. 다시 시도해 주세요.
              </p>
            )}
            {state.problem === "signupExpired" && (
              <p role="alert" className="danger">
                가입 시간이 지났어요. 다시 로그인해 주세요.
              </p>
            )}
            {state.problem === "signupChanged" && (
              <p role="alert" className="danger">
                다른 탭에서 다른 계정으로 로그인했어요. 가입할 계정으로 다시
                로그인해 주세요.
              </p>
            )}
            {buttonUnavailable && (
              <p role="alert" className="danger">
                로그인 버튼을 불러오지 못했어요. 잠시 뒤 다시 열어 주세요.
              </p>
            )}
            <GoogleButton onCredential={login} onError={buttonFailed} />
            <p className="muted">
              가입하면 Google 계정의 이메일과 계정 식별자만 저장해요.
            </p>
          </>
        )}
        {state.kind === "signingUp" && (
          <SignUp
            signup={state.signup}
            onSignedUp={show}
            onRestart={(problem) => setState({ kind: "signedOut", problem })}
            onCancel={() => show(null)}
          />
        )}
        {state.kind === "signedIn" && (
          <SignedIn user={state.user} onLoggedOut={() => show(null)} />
        )}
      </section>
    </main>
  );
}

// 칸 안의 앱 링크(/privacy 등)를 따라가면 가입 화면을 떠나 가입 진행을 잃으므로 새 탭으로 연다.
function openLinksInNewTab(e: MouseEvent<HTMLElement>) {
  const link = (e.target as HTMLElement).closest("a");
  if (!link || link.href.startsWith("mailto:")) return;
  e.preventDefault();
  window.open(link.getAttribute("href")!, "_blank", "noopener");
}

/** 가입 화면에서 바로 읽는 문서 칸. 본문은 /privacy, /terms 최신본과 같은 컴포넌트다. */
function DocumentBox({ title, version }: { title: string; version: Version }) {
  const id = useId();
  return (
    <section className="doc-box" aria-labelledby={id}>
      <div className="doc-head">
        <h2 id={id}>{title}</h2>
        <span className="muted">{koreanDate(version.effective)} 시행</span>
      </div>
      {/* 키보드로도 스크롤할 수 있게 포커스를 받는다. */}
      <div
        className="doc-scroll document"
        tabIndex={0}
        onClickCapture={openLinksInNewTab}
      >
        <version.Body />
      </div>
    </section>
  );
}

// 가입 화면(#257). 이용약관 동의 체크 하나만 받고, 처리방침은 동의 없이 링크로 알린다.
// 문서 링크는 새 탭으로 열어 이 화면의 상태를 잃지 않게 한다.
function SignUp({
  signup,
  onSignedUp,
  onRestart,
  onCancel,
}: {
  signup: Signup;
  onSignedUp: (user: User | null) => void;
  // 이 화면으로는 가입할 수 없어 Google 로그인부터 다시 해야 할 때
  onRestart: (problem: "signupExpired" | "signupChanged") => void;
  onCancel: () => void;
}) {
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const join = async () => {
    setBusy(true);
    setFailed(false);
    try {
      onSignedUp(await signUp(signup.id));
    } catch (e) {
      const code = e instanceof AuthError ? e.code : undefined;
      if (code === "AUTH:SIGNUP_EXPIRED") onRestart("signupExpired");
      else if (code === "AUTH:ACCOUNT_MISMATCH") onRestart("signupChanged");
      else {
        setFailed(true);
        setBusy(false);
      }
    }
  };

  return (
    <>
      <p className="brand">Dragram</p>
      <div className="title">
        <h1>거의 다 됐어요</h1>
        <p className="secondary">
          아래 내용을 확인하고 가입하면 확장 프로그램을 연결할 수 있어요.
        </p>
      </div>
      <div className="account">
        <span className="avatar" aria-hidden="true">
          {signup.email[0].toUpperCase()}
        </span>
        <span className="account-text">
          <span className="label">Google 계정</span>
          <strong>{signup.email}</strong>
        </span>
      </div>
      {failed && (
        <p role="alert" className="danger">
          가입하지 못했어요. 다시 시도해 주세요.
        </p>
      )}
      {/* 처리방침은 동의받지 않고 보여 주기만 한다(#257). 동의 체크는 아래 이용약관 하나다. */}
      <DocumentBox title="개인정보처리방침" version={POLICIES[0]} />
      <DocumentBox title="이용약관" version={TERMS[0]} />
      {/* 박스 전체가 체크 상태를 따라 바뀐다. 14세 안내는 체크박스 이름에 넣지 않으려고 label 밖에 둔다. */}
      <div className="terms-box">
        <label className="terms-check">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
          />
          <span>이용약관에 동의해요</span>
        </label>
        <p className="hint">Dragram은 만 14세 이상만 쓸 수 있어요.</p>
      </div>
      <button
        type="button"
        className="primary-button"
        disabled={!agreed || busy}
        onClick={join}
      >
        가입하기
      </button>
      <button
        type="button"
        className="text-button"
        disabled={busy}
        onClick={onCancel}
      >
        취소
      </button>
    </>
  );
}

type Problem =
  | "logoutFailed"
  | "withdrawFailed"
  | "accountChanged"
  | "extensionMissing"
  | "connectFailed";

const PROBLEMS: Record<Problem, string> = {
  logoutFailed: "로그아웃하지 못했어요. 다시 시도해 주세요.",
  withdrawFailed: "탈퇴하지 못했어요. 다시 시도해 주세요.",
  accountChanged:
    "다른 계정으로 로그인되어 있어요. 페이지를 새로 고친 뒤 다시 확인해 주세요.",
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
        // 다른 탭이 다른 계정으로 로그인했으면 토큰은 그 계정 것이다. 화면의 계정으로 착각해 넘기지 않는다.
        if (account !== user.account) setProblem("accountChanged");
        else if (await sendToExtension({ type: "connect", token, account }))
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
        await withdraw(user.account);
      } catch (e) {
        // 실패하면 계정이 남아 있으므로 로그인한 상태를 그대로 보인다.
        setProblem(
          e instanceof AuthError && e.status === 409
            ? "accountChanged"
            : "withdrawFailed",
        );
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
          확장 프로그램 연결, 사용량 기록을 지워요. 지운 기록은 되돌릴 수
          없어요. 원문 없이 여러 사용자가 함께 쓰는 문장 분석(번역·문법)은
          남아요. 같은 Google 계정으로 오늘 다시 가입하면 오늘 쓴 사용량 한도는
          이어져요.
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
      <a className="secondary-button" href="/sentences">
        내 기록
      </a>
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
