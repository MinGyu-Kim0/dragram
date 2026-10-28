import type { ComponentType, ReactNode } from "react";
import { Link, useParams } from "react-router";
import SiteLayout, { Section } from "./SiteLayout";
import { koreanDate } from "./koreanDate";

// 시행일별 버전이 있는 문서(처리방침, 약관). /<path>는 최신본, /<path>/<시행일>은 그 버전을 보여 준다.
// 개정할 때는 새 시행일 파일을 만들어 versions 맨 앞에 넣고, 이전 파일은 고치지 않는다.

export type Version = { effective: string; Body: ComponentType };

function VersionedDocument({
  title,
  path,
  versions,
  changeTitle,
  changeNote,
}: {
  title: string;
  path: string;
  versions: Version[];
  changeTitle: string;
  changeNote?: ReactNode;
}) {
  const { version } = useParams();
  const shown = version
    ? versions.find((v) => v.effective === version)
    : versions[0];

  return (
    <SiteLayout>
      <article className="document">
        <h1>{title}</h1>
        {shown ? (
          <>
            <p className="muted">시행일: {koreanDate(shown.effective)}</p>
            <shown.Body />
            <Section title={changeTitle}>
              {changeNote}
              <ul>
                {versions.map((v) => (
                  <li key={v.effective}>
                    <Link to={`/${path}/${v.effective}`}>
                      {koreanDate(v.effective)} 시행
                    </Link>
                  </li>
                ))}
              </ul>
            </Section>
          </>
        ) : (
          <>
            <p>
              {version}에 시행한 {title}은 없습니다.
            </p>
            <Link to={`/${path}`}>최신 {title} 보기</Link>
          </>
        )}
      </article>
    </SiteLayout>
  );
}

export default VersionedDocument;
