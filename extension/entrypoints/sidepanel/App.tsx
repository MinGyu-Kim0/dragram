import { useCallback, useEffect, useRef, useState } from "react";
import {
  receiveAnalysisRequests,
  type AnalysisRequest,
} from "@/utils/analysis-request";
import {
  AnalysisFailed,
  analyzeSentence,
  LoginRequired,
  logoutExtension,
  type Analysis,
  type CheckingItem,
  type GrammarItem,
  type Translation,
  type WordItem,
} from "@/utils/api";
import { loadToken, watchConnection } from "@/utils/auth";
import { WEB_ORIGIN } from "@/utils/external-messages";
import { createLimiter } from "@/utils/limiter";
import {
  fetchNames,
  removeName,
  saveName,
  type DesignatedName,
} from "@/utils/names";
import {
  fetchMyItems,
  itemKey,
  removeMyItem,
  saveMyItem,
  type Example,
  type ItemKind,
  type ItemState,
} from "@/utils/my-items";
import type { MyItems } from "./MyItems";
import { SentenceView, type ResultTab, type SentenceResult } from "./Sentence";
import { ThemeButton } from "./ThemeButton";
import { usePreference } from "./use-preference";

// 서버에 동시에 보내는 문장 분석 요청 수. 문장 수에는 상한이 없어서(#23), 긴 글을 골라도
// 서버에 한꺼번에 몰리지 않게 한다. 회차가 바뀌어도 이전 회차의 진행 중인 요청까지 센다.
// 비용은 사용자별 토큰 한도로, 서버 쪽 동시 요청 제한은 #28에서 한다.
const MAX_CONCURRENT_REQUESTS = 5;

// 결과와 페이지에 회차 ID를 붙여, 지금 요청의 것만 쓴다.
interface Results {
  requestId: string;
  bySentence: Record<number, SentenceResult | undefined>;
}

interface Page {
  requestId: string;
  index: number;
}

function App() {
  const [request, setRequest] = useState<AnalysisRequest>();
  const [results, setResults] = useState<Results>();
  const [page, setPage] = useState<Page>();
  const [tab, setTab] = useState<ResultTab>("grammar");
  const [showHandles, toggleHandles] = usePreference("showDragHandles");
  const [showRuby, toggleRuby] = usePreference("showRuby");
  // 패널 하나에서 모든 회차가 함께 쓰는 동시 요청 한도
  const [limiter] = useState(() => createLimiter(MAX_CONCURRENT_REQUESTS));
  // 지금 회차에서 실패한 문장을 다시 분석한다(문장 번호). 회차마다 새로 정한다.
  const retry = useRef<(index: number) => void>(undefined);
  // 확장 토큰이 있는지(웹에서 연결했는지). 처음 읽기 전에는 undefined다(#109).
  const [connected, setConnected] = useState<boolean>();
  // 로그인이 필요해 분석하지 못한 요청이 있다. 연결되면 다시 분석한다.
  const waitingForLogin = useRef(false);
  // 지정한 이름(#136). 연결되면 한 번 받고, 지정·해제하면 열린 모든 문장 페이지에 바로 쓴다.
  const [names, setNames] = useState<DesignatedName[]>([]);
  // 로그인 세대. 로그아웃(다른 계정으로 바꾼 연결 포함)하면 올라, 목록을 새로 받고 이전 로그인에서
  // 보낸 이름 요청의 늦은 응답은 버린다. 다른 사람의 지정한 이름이 섞이지 않게 한다(PR #167 리뷰).
  const [login, setLogin] = useState(0);
  const loginRef = useRef(0);
  // 끝난 저장·해제 수. 목록을 받는 사이 바뀌었으면 그 목록은 옛것이라 다시 받는다.
  const edits = useRef(0);
  // 내 일본어 항목 상태(#321, 종류:ID → 추가·숨김). 지정한 이름처럼 연결되면 받고 로그인 세대로 거른다.
  const [itemStates, setItemStates] = useState<ReadonlyMap<string, ItemState>>(
    new Map(),
  );
  const itemEdits = useRef(0);
  const itemQueues = useRef(new Map<string, Promise<unknown>>());
  // 기다리던 요청이 있으면 회차를 새로 매겨 같은 문장들을 처음부터 다시 분석한다.
  const resumeAfterLogin = useCallback(() => {
    if (!waitingForLogin.current) return;
    waitingForLogin.current = false;
    setRequest((current) => current && { ...current, id: crypto.randomUUID() });
  }, []);

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
          waitingForLogin.current = false;
          setRequest(undefined);
          setResults(undefined);
          setPage(undefined);
          setNames([]);
          setItemStates(new Map());
          loginRef.current += 1;
          setLogin(loginRef.current);
        },
      }),
    [resumeAfterLogin],
  );

  useEffect(() => {
    if (!connected) return;
    let active = true;
    const load = () => {
      const seen = edits.current;
      fetchNames().then(
        (loaded) => {
          if (!active) return;
          if (edits.current !== seen) load();
          else setNames(loaded);
        },
        // 받지 못하면 이름 없이 보인다. 401이면 api가 토큰을 지워 로그인 안내가 보인다.
        () => {},
      );
    };
    load();
    return () => {
      active = false;
    };
  }, [connected, login]);

  useEffect(() => {
    if (!connected) return;
    let active = true;
    const load = () => {
      const seen = itemEdits.current;
      fetchMyItems().then(
        (loaded) => {
          if (!active) return;
          if (itemEdits.current !== seen) load();
          else
            setItemStates(
              new Map(
                loaded.map((item) => [itemKey(item.kind, item.id), item.state]),
              ),
            );
        },
        // 받지 못하면 숨긴 카드 없이 보인다.
        () => {},
      );
    };
    load();
    return () => {
      active = false;
    };
  }, [connected, login]);

  useEffect(() => {
    // 이 패널이 열린 창의 요청만 받는다.
    let active = true;
    let stop: (() => void) | undefined;
    browser.windows.getCurrent().then((window) => {
      if (active && window.id !== undefined) {
        stop = receiveAnalysisRequests(window.id, setRequest);
      }
    });
    return () => {
      active = false;
      stop?.();
    };
  }, []);

  useEffect(() => {
    if (!request) return;
    // 모든 문장을 바로 분석하되 동시 요청 한도 안에서 보낸다. 번역이 오면 먼저 보이고
    // 문법·단어가 오면 채운다. 같은 문장은 한 번만 분석하고 결과를 함께 쓴다.
    // 새 요청이 오면 이전 요청의 늦은 응답은 버리고 남은 문장도 보내지 않는다.
    let current = true;
    const requestId = request.id;
    const save = (index: number, result: SentenceResult | undefined) => {
      if (!current) return;
      setResults((previous) => ({
        requestId,
        bySentence: {
          ...(previous?.requestId === requestId ? previous.bySentence : {}),
          [index]: result,
        },
      }));
    };
    // 같은 문장은 한 번만 분석하고, 그 문장이 나온 모든 페이지에 결과를 넣는다.
    const indicesByText = new Map<string, number[]>();
    request.sentences.forEach(({ text }, index) => {
      indicesByText.set(text, [...(indicesByText.get(text) ?? []), index]);
    });
    const analyze = (text: string) => {
      const indices = indicesByText.get(text)!;
      const saveAll = (result: SentenceResult | undefined) =>
        indices.forEach((index) => save(index, result));
      // LLM 없이 확정한 문법은 번역보다 먼저 와서, 번역이 와도 함께 보인다.
      let earlyGrammar: GrammarItem[] | undefined;
      let checking: CheckingItem[] | undefined;
      // 사전에서 찾은 단어도 grammar 이벤트로 먼저 온다(#96).
      let earlyWords: WordItem[] | undefined;
      let translated: Translation | undefined;
      // stale 분석의 옛 결과. 있으면 새 결과가 다 올 때까지 그것만 보이고 중간 이벤트는 버린다.
      let previous: Analysis | undefined;
      limiter
        .schedule(
          () =>
            analyzeSentence(
              text,
              (translation) => {
                if (previous) return;
                translated = translation;
                saveAll({
                  status: "translated",
                  translation,
                  earlyGrammar,
                  checking,
                  earlyWords,
                });
              },
              (grammar, waiting, words) => {
                if (previous) return;
                earlyGrammar = grammar;
                checking = waiting;
                earlyWords = words;
                saveAll({
                  status: "early",
                  earlyGrammar,
                  checking,
                  earlyWords,
                });
              },
              (old) => {
                previous = old;
                saveAll({ status: "reanalyzing", previous });
              },
              // 첫 LLM 응답이 판정한 문법과 고른 뜻(#97). 번역이 왔으면 함께 보인다.
              (grammar, waiting, words) => {
                if (previous) return;
                earlyGrammar = grammar;
                checking = waiting;
                earlyWords = words;
                saveAll(
                  translated
                    ? {
                        status: "translated",
                        translation: translated,
                        earlyGrammar,
                        checking,
                        earlyWords,
                      }
                    : {
                        status: "early",
                        earlyGrammar: earlyGrammar ?? [],
                        checking: checking ?? [],
                        earlyWords,
                      },
                );
              },
              // 검증 전 번역 앞부분(#303). 실패하면 실패 결과가 이것을 지운다.
              (partial) => {
                if (previous) return;
                saveAll({
                  status: "translated",
                  translation: partial,
                  earlyGrammar,
                  checking,
                  earlyWords,
                });
              },
            ),
          () => !current,
        )
        .then(
          (analysis) => saveAll({ status: "done", analysis }),
          (error: unknown) => {
            // 토큰이 없거나 거부됐다. api가 토큰을 지워 로그인 안내가 보이고, 연결되면 다시
            // 분석한다.
            if (error instanceof LoginRequired) {
              // 이미 지나간 회차의 늦은 401은 지금 회차와 상관없다.
              if (!current) return;
              waitingForLogin.current = true;
              // 401이 오기 전에 이미 다시 연결했으면 연결 알림이 지나갔으므로 바로 다시 분석한다.
              loadToken().then((token) => {
                if (token) resumeAfterLogin();
              });
              return;
            }
            saveAll({
              status: "failed",
              // 다시 분석하다 실패하면 옛 결과만 남기고 그사이 받은 새 번역·문법은 버린다.
              ...(error instanceof AnalysisFailed
                ? error.previous
                  ? { previous: error.previous }
                  : {
                      translation: error.translation,
                      earlyGrammar: error.earlyGrammar,
                      code: error.code,
                    }
                : {}),
            });
          },
        );
    };
    indicesByText.forEach((_, text) => analyze(text));
    // 다시 시도는 처음 분석과 같은 규칙(같은 문장 묶기, 동시 요청 한도, 회차)으로 보낸다.
    // 결과는 처음처럼 비우고 다시 받는다. 비어 있는 동안은 버튼이 없어 겹쳐 보내지 않는다.
    retry.current = (index) => {
      const { text } = request.sentences[index]!;
      indicesByText.get(text)!.forEach((i) => save(i, undefined));
      analyze(text);
    };
    return () => {
      current = false;
    };
  }, [request, limiter, resumeAfterLogin]);

  const pageIndex = page && page.requestId === request?.id ? page.index : 0;
  const sentence = request?.sentences[pageIndex];
  const result =
    results && results.requestId === request?.id
      ? results.bySentence[pageIndex]
      : undefined;
  const goTo = (index: number) => setPage({ requestId: request!.id, index });
  const nameMap = new Map(
    names.map(({ surface, reading }) => [surface, reading]),
  );
  const onSaveName = async (surface: string, reading: string) => {
    const started = loginRef.current;
    const saved = await saveName(surface, reading);
    if (loginRef.current !== started) return;
    edits.current += 1;
    setNames((current) => [
      ...current.filter((name) => name.surface !== saved.surface),
      saved,
    ]);
  };
  const onRemoveName = async (surface: string) => {
    const started = loginRef.current;
    await removeName(surface);
    if (loginRef.current !== started) return;
    edits.current += 1;
    setNames((current) => current.filter((name) => name.surface !== surface));
  };

  // 같은 항목의 바꾸기 요청은 앞 요청이 끝난 뒤 보낸다. 같은 뜻이 여러 줄에 있을 때 응답이 뒤바뀌어
  // 화면이 서버와 어긋나지 않게 한다. 기다리는 사이 로그아웃(계정 변경)했으면 보내지 않는다. 그
  // 요청이 다음 계정의 토큰으로 나가지 않게 하기 위해서다(PR #327 리뷰).
  const inOrder = (key: string, task: () => Promise<void>): Promise<void> => {
    const started = loginRef.current;
    const previous = itemQueues.current.get(key) ?? Promise.resolve();
    const next = previous
      .catch(() => {})
      .then(() => (loginRef.current === started ? task() : undefined));
    itemQueues.current.set(key, next);
    return next;
  };
  const myItems: MyItems = {
    states: itemStates,
    save: (kind: ItemKind, id: number, state: ItemState, example?: Example) =>
      inOrder(itemKey(kind, id), async () => {
        const started = loginRef.current;
        const saved = await saveMyItem(kind, id, state, example);
        if (loginRef.current !== started) return;
        itemEdits.current += 1;
        setItemStates((current) =>
          new Map(current).set(itemKey(saved.kind, saved.id), saved.state),
        );
      }),
    remove: (kind: ItemKind, id: number) =>
      inOrder(itemKey(kind, id), async () => {
        const started = loginRef.current;
        await removeMyItem(kind, id);
        if (loginRef.current !== started) return;
        itemEdits.current += 1;
        setItemStates((current) => {
          const next = new Map(current);
          next.delete(itemKey(kind, id));
          return next;
        });
      }),
  };

  if (connected === false) {
    return (
      <main>
        <header className="panel-header">
          <h1>Dragram</h1>
          <ThemeButton />
        </header>
        <LoginPrompt />
      </main>
    );
  }

  return (
    <main>
      <header className="panel-header">
        <h1>Dragram</h1>
        <div className="header-actions">
          <ThemeButton />
          {connected && (
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
      {request && request.sentences.length > 1 && (
        <nav className="pager" aria-label="문장">
          <button
            type="button"
            aria-label="이전 문장"
            disabled={pageIndex === 0}
            onClick={() => goTo(pageIndex - 1)}
          >
            ‹
          </button>
          <span>
            {pageIndex + 1} / {request.sentences.length}
          </span>
          <button
            type="button"
            aria-label="다음 문장"
            disabled={pageIndex === request.sentences.length - 1}
            onClick={() => goTo(pageIndex + 1)}
          >
            ›
          </button>
        </nav>
      )}
      {sentence && (
        <SentenceView
          // '사전 단어 보기'는 그 페이지의 화면 상태라 페이지마다 새로 시작한다.
          key={`${request!.id}-${pageIndex}`}
          text={sentence.text}
          selection={sentence.selection}
          showHandles={showHandles}
          onToggleHandles={toggleHandles}
          showRuby={showRuby}
          onToggleRuby={toggleRuby}
          result={result}
          tab={tab}
          onTabChange={setTab}
          onRetry={() => retry.current?.(pageIndex)}
          names={nameMap}
          onSave={onSaveName}
          onRemove={onRemoveName}
          items={myItems}
        />
      )}
    </main>
  );
}

// 로그인 전(DESIGN 사이드 패널 '로그인 전'). 웹 '로그인·확장 연결' 화면에서 연결한다.
function LoginPrompt() {
  return (
    <section className="login-prompt">
      <h2>로그인이 필요해요</h2>
      <p>
        문장을 분석하려면 웹에서 Google 계정으로 로그인하고 확장 프로그램을
        연결해 주세요.
      </p>
      <button
        type="button"
        className="primary-button"
        onClick={() => browser.tabs.create({ url: `${WEB_ORIGIN}/connect` })}
      >
        로그인하고 연결하기
      </button>
      <p className="muted">
        분석할 문장은 Dragram 서버로 보내 분석하고, 분석에는 OpenAI를 써요.
      </p>
    </section>
  );
}

export default App;
