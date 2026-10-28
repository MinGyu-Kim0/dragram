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

function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <div className="site">
      <header className="site-header">
        <Link to="/" className="logo">
          Dragram
        </Link>
      </header>
      <main>{children}</main>
      <footer>
        <nav aria-label="사이트">
          <Link to="/">Dragram 홈</Link>
          <Link to="/privacy">개인정보처리방침</Link>
          <Link to="/terms">이용약관</Link>
        </nav>
        <p>
          단어 정보: <a href={JMDICT_URL}>JMdict</a> (EDRDG,{" "}
          <a href={CC_BY_SA_URL}>CC BY-SA 4.0</a>)
        </p>
      </footer>
    </div>
  );
}

export default SiteLayout;
