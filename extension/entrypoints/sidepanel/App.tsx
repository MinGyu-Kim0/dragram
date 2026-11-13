import { useEffect, useState } from "react";
import { logoutExtension } from "@/utils/api";
import { watchConnection } from "@/utils/auth";
import { LoginPrompt } from "./LoginPrompt";
import type { ResultTab } from "./ResultTabs";
import { SentenceView } from "./Sentence";
import { UpdatePrompt } from "./UpdatePrompt";
import { GuideButton } from "./GuideButton";
import { Pager } from "./Pager";
import { Logo } from "./Logo";
import { ThemeButton } from "./ThemeButton";
import { useDesignatedNames } from "./use-designated-names";
import { useLoginGeneration } from "./use-login-generation";
import { useMyItemStates } from "./use-my-item-states";
import { useSentenceAnalysis } from "./use-sentence-analysis";
import { usePreference } from "./use-preference";
import {
  loadHighlightStyle,
  loadShowRuby,
  saveHighlightStyle,
  saveShowRuby,
} from "@/utils/preferences";
import { useUpdateRequired } from "./use-update-required";

// 페이지에 회차 ID를 붙여, 지금 요청의 것만 쓴다.
interface Page {
  requestId: string;
  index: number;
}

function App() {
  const [page, setPage] = useState<Page>();
  const [tab, setTab] = useState<ResultTab>("grammar");
  const [showRuby, setShowRuby] = usePreference(
    loadShowRuby,
    saveShowRuby,
    true,
  );
  const [highlightStyle, setHighlightStyle] = usePreference(
    loadHighlightStyle,
    saveHighlightStyle,
    "marker",
  );
  // 확장 토큰이 있는지(웹에서 연결했는지). 처음 읽기 전에는 undefined다(#109).
  const [connected, setConnected] = useState<boolean>();
  const updateRequired = useUpdateRequired();
  const generation = useLoginGeneration();
  const names = useDesignatedNames(connected, generation);
  const myItems = useMyItemStates(connected, generation);
  // 이름·항목 조회 뒤에 둔다. 다시 연결하면 그 조회가 분석 요청보다 먼저 나간다.
  const analysis = useSentenceAnalysis();
  const { request, resumeAfterLogin, clear: clearAnalysis } = analysis;
  const { clear: clearNames } = names;
  const { clear: clearItems } = myItems;
  const { advance: nextLogin } = generation;

  useEffect(
    () =>
      watchConnection({
        onConnected: (now) => {
          setConnected(now);
          if (now) resumeAfterLogin();
        },
        // 로그아웃(패널·웹)했다. 보던 원문과 결과를 지워, 다음에 연결한 사람에게 보이지
        // 않게 한다. 진행 중인 회차의 늦은 응답도 버려진다.
        onSignedOut: () => {
          clearAnalysis();
          setPage(undefined);
          clearNames();
          clearItems();
          nextLogin();
        },
      }),
    [resumeAfterLogin, clearAnalysis, clearNames, clearItems, nextLogin],
  );

  const pageIndex = page && page.requestId === request?.id ? page.index : 0;
  const sentence = request?.sentences[pageIndex];
  const result = analysis.resultAt(pageIndex);
  const goTo = (index: number) => setPage({ requestId: request!.id, index });

  // 옛 확장이어도(업데이트 필요) 연결은 끊을 수 있다.
  const canLogout = connected !== false && (connected || updateRequired);

  return (
    <main>
      <header className="panel-header">
        <Logo />
        <div className="header-actions">
          <GuideButton />
          <ThemeButton />
          {canLogout && (
            <button
              type="button"
              className="text-button"
              onClick={() => logoutExtension()}
            >
              로그아웃
            </button>
          )}
        </div>
      </header>
      {connected === false ? (
        <LoginPrompt />
      ) : updateRequired ? (
        <UpdatePrompt />
      ) : (
        <>
          {request && request.sentences.length > 1 && (
            <Pager
              index={pageIndex}
              total={request.sentences.length}
              onGo={goTo}
            />
          )}
          {sentence && (
            <SentenceView
              // '사전 단어 보기'는 그 페이지의 화면 상태라 페이지마다 새로 시작한다.
              key={`${request!.id}-${pageIndex}`}
              text={sentence.text}
              showRuby={showRuby}
              onToggleRuby={() => setShowRuby(!showRuby)}
              highlightStyle={highlightStyle}
              onHighlightStyleChange={setHighlightStyle}
              result={result}
              tab={tab}
              onTabChange={setTab}
              onRetry={() => analysis.retry(pageIndex)}
              names={names.names}
              onSave={names.save}
              onRemove={names.remove}
              items={myItems.items}
            />
          )}
        </>
      )}
    </main>
  );
}

export default App;
