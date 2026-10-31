import { useId, type ReactNode } from "react";
import { Link } from "react-router";
import "./site.css";

// 로그인 없이 여는 소개·처리방침·약관 화면의 공통 틀(DESIGN §4 '웹 — Phase 1').

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

function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <div className="site">
      <header className="site-header">
        <div className="site-inner">
          <Link to="/" className="logo">
            <LogoMark />
            Dragram
          </Link>
          <Link to="/connect" className="header-link">
            로그인
          </Link>
        </div>
      </header>
      <main>{children}</main>
      <footer>
        <div className="site-inner">
          <nav aria-label="사이트">
            <Link to="/">Dragram 홈</Link>
            <Link to="/privacy">개인정보처리방침</Link>
            <Link to="/terms">이용약관</Link>
          </nav>
          <p>
            단어 정보: <a href={JMDICT_URL}>JMdict</a> (EDRDG,{" "}
            <a href={CC_BY_SA_URL}>CC BY-SA 4.0</a>)
          </p>
        </div>
      </footer>
    </div>
  );
}

export default SiteLayout;
