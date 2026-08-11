(() => {
  const JAPANESE_TEXT = /[\u3040-\u30ff\u3400-\u9fff]/;
  const MODELS = ["gpt-5.6-luna", "gpt-5.6-terra"];
  const host = document.createElement("div");
  const shadow = host.attachShadow({ mode: "closed" });
  let timer;
  let requestId = 0;
  let lastText = "";
  let enabled = true;
  let selectedModel = MODELS[0];
  let pages = [];
  let pageResults = [];
  let pageIndex = 0;
  let selectionStartedInCard = false;

  shadow.innerHTML = `
    <style>
      :host { all: initial; }
      .card { position: fixed; right: 20px; bottom: 20px; z-index: 2147483647; width: min(390px, calc(100vw - 32px)); max-height: min(680px, calc(100vh - 40px)); overflow: auto; box-sizing: border-box; border: 1px solid #cfe8dc; border-radius: 18px; padding: 18px; color: #173a2d; background: #fff; box-shadow: 0 18px 55px rgba(16, 78, 55, .22); font: 14px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Noto Sans KR", sans-serif; }
      .hidden { display: none; }
      header, .pager { display: flex; align-items: center; gap: 10px; }
      header { margin-bottom: 14px; }
      .brand { margin-right: auto; color: #14734f; font-size: 13px; font-weight: 900; letter-spacing: .12em; }
      button { border: 0; border-radius: 999px; padding: 5px 9px; color: #14734f; background: #e8f6ef; cursor: pointer; font: inherit; }
      button:disabled { cursor: default; opacity: .45; }
      button:focus-visible, a:focus-visible { outline: 3px solid #f0a868; outline-offset: 2px; }
      h2, h3, p { margin: 0; }
      h2 { margin-top: 3px; font-size: 18px; line-height: 1.4; }
      h3 { font-size: 15px; }
      .label { margin-top: 16px; color: #14734f; font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
      .muted { color: #5f776d; }
      .tokens { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 7px; }
      .token { border: 1px solid #cfe8dc; border-radius: 9px; padding: 5px 8px; background: #f3fbf7; cursor: help; }
      .grammar { margin-top: 9px; border-radius: 12px; padding: 11px; background: #f3fbf7; }
      .grammar p { margin-top: 4px; }
      .loading { display: flex; align-items: center; gap: 9px; color: #376a57; }
      .dot { width: 9px; height: 9px; border-radius: 50%; background: #1b8a61; animation: pulse 1s infinite alternate; }
      .error { color: #9b3326; }
      .pager { justify-content: center; margin-top: 16px; padding-top: 12px; border-top: 1px solid #e3efe9; }
      .pager span { min-width: 52px; text-align: center; color: #5f776d; font-size: 12px; font-weight: 700; }
      a { color: #14734f; font-weight: 700; }
      @keyframes pulse { to { opacity: .25; transform: scale(.75); } }
      @media (max-width: 540px) { .card { right: 12px; bottom: 12px; width: calc(100vw - 24px); max-height: calc(100vh - 24px); } }
    </style>
    <section class="card hidden" role="dialog" aria-label="Dragram 일본어 분석" aria-live="polite">
      <header>
        <span class="brand">DRAGRAM</span>
        <button class="close" type="button" aria-label="닫기">닫기</button>
      </header>
      <div class="body"></div>
      <nav class="pager hidden" aria-label="선택 문장 페이지">
        <button class="previous" type="button" aria-label="이전 문장">이전</button>
        <span class="page-status"></span>
        <button class="next" type="button" aria-label="다음 문장">다음</button>
      </nav>
    </section>`;

  const card = shadow.querySelector(".card");
  const body = shadow.querySelector(".body");
  const pager = shadow.querySelector(".pager");
  const previousButton = shadow.querySelector(".previous");
  const nextButton = shadow.querySelector(".next");
  const pageStatus = shadow.querySelector(".page-status");

  function resetAnalysis() {
    card.classList.add("hidden");
    pager.classList.add("hidden");
    requestId += 1;
    lastText = "";
    pages = [];
    pageResults = [];
    pageIndex = 0;
  }

  shadow.querySelector(".close").addEventListener("click", resetAnalysis);
  chrome.storage.local.get({ enabled, model: selectedModel }, (stored) => {
    enabled = stored.enabled !== false;
    if (MODELS.includes(stored.model)) selectedModel = stored.model;
  });
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local") return;
    if (changes.enabled) enabled = changes.enabled.newValue !== false;
    if (changes.model && MODELS.includes(changes.model.newValue)) {
      selectedModel = changes.model.newValue;
    }
    if (changes.enabled || changes.model) resetAnalysis();
  });
  document.addEventListener("pointerdown", (event) => {
    selectionStartedInCard = event.composedPath().includes(host);
  }, true);
  document.documentElement.appendChild(host);

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function updatePager() {
    pager.classList.toggle("hidden", pages.length < 2);
    pageStatus.textContent = `${pageIndex + 1} / ${pages.length}`;
    previousButton.disabled = pageIndex === 0;
    nextButton.disabled = pageIndex === pages.length - 1;
  }

  function showLoading(text) {
    body.replaceChildren();
    const loading = element("div", "loading");
    loading.append(element("span", "dot"), element("span", "", "형태소와 문법을 분석하고 있습니다."));
    body.append(loading, element("h2", "", text));
    card.classList.remove("hidden");
  }

  function showError(message) {
    body.replaceChildren(
      element("p", "error", message),
      element("p", "muted", "Dragram 백엔드와 .env 설정을 확인해 주세요."),
    );
    const link = element("a", "", "Dragram 열기");
    link.href = "http://localhost:5173";
    link.target = "_blank";
    link.rel = "noreferrer";
    body.append(link);
    card.classList.remove("hidden");
  }

  function addSection(label, text) {
    body.append(element("p", "label", label), element("p", "", text));
  }

  function showResult(result) {
    body.replaceChildren(element("h2", "", result.normalized_text));
    addSection("뜻", result.meaning_ko);
    addSection("문장 분석", result.explanation);
    body.append(element("p", "label", "어휘"));
    const tokens = element("div", "tokens");
    result.vocabulary.forEach((token) => {
      const chip = element("span", "token", token.surface);
      chip.title = [token.dictionary_form, token.reading_form, token.part_of_speech.join(" · ")]
        .filter(Boolean)
        .join(" / ");
      tokens.append(chip);
    });
    body.append(tokens, element("p", "label", "문법"));
    if (!result.grammars.length) body.append(element("p", "muted", "별도의 문법 패턴이 없습니다."));
    result.grammars.forEach((grammar) => {
      const item = element("article", "grammar");
      item.append(
        element("h3", "", `${grammar.name_ja} · ${grammar.name_ko}`),
        element("p", "", grammar.summary),
        element("p", "muted", grammar.evidence),
      );
      body.append(item);
    });
    card.classList.remove("hidden");
  }

  function requestPage() {
    const currentPage = pageIndex;
    const text = pages[currentPage];
    const currentRequest = ++requestId;
    showLoading(text);
    chrome.runtime.sendMessage(
      {
        type: "DRAGRAM_ANALYZE",
        payload: { text, source_url: location.href, source_title: document.title, model: selectedModel },
      },
      (response) => {
        if (currentRequest !== requestId || currentPage !== pageIndex) return;
        if (chrome.runtime.lastError) return showError("Dragram 백엔드에 연결할 수 없습니다.");
        if (!response?.ok) return showError(response?.error || "문법 분석에 실패했습니다.");
        pageResults[currentPage] = response.result;
        showResult(response.result);
      },
    );
  }

  function showPage(index) {
    if (index < 0 || index >= pages.length) return;
    pageIndex = index;
    updatePager();
    if (pageResults[index]) showResult(pageResults[index]);
    else requestPage();
  }

  previousButton.addEventListener("click", () => showPage(pageIndex - 1));
  nextButton.addEventListener("click", () => showPage(pageIndex + 1));

  function analyzeSelection() {
    if (!enabled || selectionStartedInCard) return;
    const selection = window.getSelection();
    if (selection?.anchorNode?.getRootNode() === shadow) return;
    const text = selection?.toString().trim() || "";
    if (!text || text === lastText || !JAPANESE_TEXT.test(text)) return;

    requestId += 1;
    pager.classList.add("hidden");
    pages = [];
    pageResults = [];
    const selectedPages = globalThis.Dragram.splitSentences(text).filter((page) => JAPANESE_TEXT.test(page));
    if (!selectedPages.length) return;
    if (selectedPages.some((page) => page.length > 1000)) {
      return showError("각 문장은 1000자 이하여야 합니다.");
    }

    lastText = text;
    pages = selectedPages;
    pageResults = new Array(pages.length);
    showPage(0);
  }

  document.addEventListener("selectionchange", () => {
    clearTimeout(timer);
    timer = setTimeout(analyzeSelection, 350);
  });
})();
