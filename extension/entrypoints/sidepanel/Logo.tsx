import { WEB_ORIGIN } from "@/utils/external-messages";

// 헤더 로고. 웹(web/src/site/SiteLayout.tsx LogoMark)과 같은 그림이고, 누르면 웹 페이지를 새 탭으로 연다.
export function Logo() {
  return (
    <h1>
      <a
        href={`${WEB_ORIGIN}/`}
        target="_blank"
        rel="noreferrer"
        className="logo"
      >
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
        Dragram
      </a>
    </h1>
  );
}
