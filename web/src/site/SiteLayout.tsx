import { useEffect, useId, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { currentUser, type User } from "../connect/auth";
import { logoutAndDisconnect } from "../connect/extension";
import ThemeButton from "./ThemeButton";
import "./site.css";

// 웹 화면의 공통 틀(DESIGN §4 '웹 — Phase 2' 공통 헤더: 로고 + 메뉴 + 계정).

export const JMDICT_URL = "https://www.edrdg.org/jmdict/j_jmdict.html";
export const CC_BY_SA_URL = "https://creativecommons.org/licenses/by-sa/4.0/";

/** 연락 메일. 정해지기 전에는 빈 메일 링크 대신 '연락처 준비 중'을 보인다. */
export function ContactEmail() {
  const email = import.meta.env.VITE_CONTACT_EMAIL;
  return email ? (
    <a href={`mailto:${email}`}>{email}</a>
  ) : (
    <span>연락처 준비 중</span>
  );
}

/** 문서의 표. 첫 열은 행 제목이다. 열이 많으면 좁은 화면에서 표만 가로로 스크롤하고, 그 영역은
 * 키보드로도 스크롤할 수 있게 포커스를 받는다. label은 스크롤 영역의 이름이다. */
export function Table({
  label,
  head,
  rows,
}: {
  label: string;
  head: string[];
  rows: ReactNode[][];
}) {
  return (
    <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
      <table>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([first, ...rest], i) => (
            <tr key={i}>
              <th scope="row">{first}</th>
              {rest.map((cell, j) => (
                <td key={j}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}

/** 헤더 로고(와이어프레임의 32 viewBox 변형): 형광펜 두 줄 + 드래그 핸들 + 커서 */
function LogoMark() {
  return (
    <svg
      className="logo-mark"
      width="26"
      height="26"
      viewBox="0 0 32 32"
      aria-hidden="true"
    >
      <rect
        className="logo-pen"
        x="10"
        y="5"
        width="19"
        height="8.5"
        rx="2.6"
      />
      <rect
        className="logo-pen"
        x="3"
        y="15.5"
        width="15"
        height="8.5"
        rx="2.6"
      />
      <rect
        className="logo-ink"
        x="8.6"
        y="3"
        width="2.8"
        height="12.5"
        rx="1.4"
      />
      <path
        className="logo-ink logo-cursor"
        d="M16.5 18 L16.5 31.6 L20.1 28.4 L22.5 34 L25.3 32.8 L22.9 27.2 L27.3 27.2 Z"
        strokeWidth="2.2"
        strokeLinejoin="round"
        paintOrder="stroke"
      />
    </svg>
  );
}

/** 로그인 후 헤더의 계정 메뉴: 이메일, 로그아웃 */
function AccountMenu({
  user,
  onLoggedOut,
}: {
  user: User;
  onLoggedOut: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const signOut = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await logoutAndDisconnect();
    } catch {
      // 세션이 남아 있으므로 로그인한 헤더를 그대로 둔다.
      setFailed(true);
      setBusy(false);
      return;
    }
    onLoggedOut();
  };

  return (
    <details
      className="account-menu"
      // Escape로 닫고 포커스를 메뉴 단추로 돌려준다.
      onKeyDown={(e) => {
        if (e.key !== "Escape" || !e.currentTarget.open) return;
        e.currentTarget.open = false;
        e.currentTarget.querySelector("summary")?.focus();
      }}
    >
      <summary>
        <span aria-hidden="true">{user.email.charAt(0).toUpperCase()}</span>
        <span className="visually-hidden">계정 메뉴</span>
      </summary>
      <div className="account-panel">
        <p className="account-email">{user.email}</p>
        {/* 좁은 폭에서는 헤더 메뉴를 숨기고 이 안에 접어 둔다. */}
        <Link to="/sentences" className="narrow-only">
          내 기록
        </Link>
        {failed && (
          <p role="alert" className="danger">
            로그아웃하지 못했어요. 다시 시도해 주세요.
          </p>
        )}
        <button
          type="button"
          className="secondary-button"
          disabled={busy}
          onClick={signOut}
        >
          로그아웃
        </button>
      </div>
    </details>
  );
}

/** children이 함수면 로그인 확인 뒤에 로그인한 사용자(없으면 null)로 그린다. 확인 중에는 헤더만 보인다.
 * 확인 자체가 실패하면(서버 오류) user는 null, failed는 true다. 헤더에는 로그인도 계정도 보이지 않는다. */
function SiteLayout({
  children,
}: {
  children: ReactNode | ((user: User | null, failed: boolean) => ReactNode);
}) {
  // undefined는 확인 중이다.
  const [user, setUser] = useState<User | null | "failed">();
  const navigate = useNavigate();

  useEffect(() => {
    currentUser().then(setUser, () => setUser("failed"));
  }, []);

  const failed = user === "failed";
  const content =
    typeof children === "function"
      ? user !== undefined && children(failed ? null : user, failed)
      : children;

  return (
    <div className="site">
      <header className="site-header">
        <div className="site-inner">
          <Link to="/" className="logo">
            <LogoMark />
            Dragram
          </Link>
          <ThemeButton />
          {user === null && (
            <Link to="/connect" className="header-link">
              로그인
            </Link>
          )}
          {user && !failed && (
            <>
              <nav aria-label="메뉴">
                <Link to="/sentences" className="header-link">
                  내 기록
                </Link>
              </nav>
              <AccountMenu
                user={user}
                onLoggedOut={() => {
                  setUser(null);
                  navigate("/");
                }}
              />
            </>
          )}
        </div>
      </header>
      <main>{content}</main>
      <footer>
        <div className="site-inner">
          {/* 칸 사이의 | 는 CSS가 그린다(링크 밖에 두어 누르는 범위에 들지 않게). */}
          <nav aria-label="사이트">
            <ul className="footer-row">
              <li>
                <Link to="/">Dragram 홈</Link>
              </li>
              <li>
                <Link to="/privacy">개인정보처리방침</Link>
              </li>
              <li>
                <Link to="/terms">이용약관</Link>
              </li>
              <li>
                문의: <ContactEmail />
              </li>
            </ul>
          </nav>
          <ul className="footer-row footer-credits">
            <li>
              단어 정보: <a href={JMDICT_URL}>JMdict</a> (EDRDG,{" "}
              <a href={CC_BY_SA_URL}>CC BY-SA 4.0</a>)
            </li>
          </ul>
        </div>
      </footer>
    </div>
  );
}

export default SiteLayout;
