// 페이지에서 고른 범위를 문장 단위로 넓혀 문장 목록을 만든다(#16). 탭에 주입되어 실행되므로
// DOM만 쓰고 확장 API는 쓰지 않는다. 정규화는 하지 않는다(서버가 한다).

export interface ExtractedSentence {
  // 루비 읽기(rt·rp)를 뺀 문장 원문
  text: string;
  // 이 문장 안에서 실제로 드래그한 범위. UTF-16 기준 반열린 구간 [start, end)
  selection: { start: number; end: number };
}

// 블록 경계·줄바꿈 자리에 넣는 표시. 이 글자에서는 문장이 반드시 끊긴다.
const BREAK = "\n";
const SENTENCE_ENDS = "。！？!?";
const OPENING_QUOTES = "「『（(【〈《“‘";
const CLOSING_QUOTES = "」』）)】〉》”’";
// 문장 앞뒤에서 떼어 낼 공백. JS의 \s는 전각 공백(U+3000)도 포함한다.
const LEADING_SPACES = /^\s*/;
const TRAILING_SPACES = /\s*$/;
// 본문으로 보지 않는 요소. rt·rp는 루비 읽기 글자다.
const SKIPPED_TAGS = new Set([
  "RT",
  "RP",
  "SCRIPT",
  "STYLE",
  "NOSCRIPT",
  "TEMPLATE",
]);
// 이 display 값은 줄을 바꾸지 않는다. 나머지(block, list-item, table-cell, flex 등)는 블록 경계다.
const INLINE_DISPLAYS = new Set([
  "inline",
  "inline-block",
  "inline-flex",
  "inline-grid",
  "inline-table",
  "contents",
  "ruby",
  "ruby-base",
  "ruby-text",
  "ruby-base-container",
  "ruby-text-container",
]);
// 개행을 화면에서도 줄바꿈으로 보이는 white-space 값
const PRESERVED_NEWLINES = new Set([
  "pre",
  "pre-wrap",
  "pre-line",
  "break-spaces",
]);

interface TextEntry {
  node: Text;
  start: number;
}

export function extractSentences(range: Range): ExtractedSentence[] {
  const root = blockAncestor(range.commonAncestorContainer);
  const { text, entries } = collectText(root);
  const from = toIndex(range.startContainer, range.startOffset, text, entries);
  const to = toIndex(range.endContainer, range.endOffset, text, entries);

  const sentences: ExtractedSentence[] = [];
  for (const [start, end] of splitSentences(text)) {
    const overlaps =
      from === to ? start <= from && from < end : start < to && from < end;
    if (!overlaps) continue;
    sentences.push({
      text: text.slice(start, end),
      selection: {
        start: Math.max(from, start) - start,
        end: Math.min(to, end) - start,
      },
    });
  }
  return sentences;
}

// 문장은 블록 경계를 넘지 않으므로, 고른 범위를 감싸는 가장 가까운 블록만 읽으면 된다.
function blockAncestor(node: Node): Element {
  let element = node instanceof Element ? node : node.parentElement;
  while (element && element !== document.body && !isBlock(element)) {
    element = element.parentElement;
  }
  return element ?? document.body;
}

function isBlock(element: Element): boolean {
  return !INLINE_DISPLAYS.has(getComputedStyle(element).display);
}

// 본문 글자를 이어 붙인다. 블록 경계와 줄바꿈 자리에는 BREAK를 넣는다. 화면에서 공백으로
// 보이는 개행은 공백으로 바꾼다(글자 수가 그대로라 텍스트 노드 위치와 바로 대응한다).
function collectText(root: Element): { text: string; entries: TextEntry[] } {
  let text = "";
  const entries: TextEntry[] = [];

  const visit = (node: Node) => {
    if (node instanceof Text) {
      const style = node.parentElement && getComputedStyle(node.parentElement);
      // visibility: hidden은 자리는 남기고 글자를 숨긴다. 보이지 않는 글자는 문장에 넣지 않는다.
      // visibility는 상속되므로 글자를 직접 감싼 요소의 값만 보면 된다.
      if (style && style.visibility !== "visible") return;
      const keepsNewlines =
        style !== null && PRESERVED_NEWLINES.has(style.whiteSpace);
      entries.push({ node, start: text.length });
      text += keepsNewlines
        ? node.data.replace(/\r/g, BREAK)
        : node.data.replace(/[\r\n\t]/g, " ");
      return;
    }
    if (!(node instanceof Element) || SKIPPED_TAGS.has(node.tagName)) return;
    if (getComputedStyle(node).display === "none") return;
    if (node.tagName === "BR") {
      text += BREAK;
      return;
    }
    const block = node !== root && isBlock(node);
    if (block) text += BREAK;
    node.childNodes.forEach(visit);
    if (block) text += BREAK;
  };

  visit(root);
  return { text, entries };
}

// 범위의 경계 지점(노드, 오프셋)을 이어 붙인 글자의 위치로 바꾼다.
function toIndex(
  container: Node,
  offset: number,
  text: string,
  entries: TextEntry[],
): number {
  const entry = entries.find((candidate) => candidate.node === container);
  if (entry) return entry.start + Math.min(offset, entry.node.length);
  // 요소 안의 지점이거나 읽지 않은 글자(rt 등) 안이면, 그 지점 뒤의 첫 본문 글자 위치다.
  const point = document.createRange();
  point.setStart(container, offset);
  const next = entries.find(
    (candidate) => point.comparePoint(candidate.node, 0) >= 0,
  );
  return next ? next.start : text.length;
}

// 문장마다 앞뒤 공백을 뺀 [시작, 끝) 구간을 돌려준다.
function splitSentences(text: string): [number, number][] {
  const sentences: [number, number][] = [];
  const push = (start: number, end: number) => {
    const sentence = text.slice(start, end);
    const lead = LEADING_SPACES.exec(sentence)![0].length;
    if (lead === sentence.length) return;
    const trail = TRAILING_SPACES.exec(sentence)![0].length;
    sentences.push([start + lead, end - trail]);
  };

  let start = 0;
  let depth = 0;
  // 문장 첫머리에서 열린 인용(대사)인가. 이런 인용은 「…。」 뒤에서 문장이 끝난다.
  let quoteOpensSentence = false;
  let i = 0;
  while (i < text.length) {
    const ch = text[i]!;
    if (ch === BREAK) {
      push(start, i);
      start = i + 1;
      depth = 0;
      i += 1;
      continue;
    }
    if (OPENING_QUOTES.includes(ch)) {
      if (depth === 0) quoteOpensSentence = text.slice(start, i).trim() === "";
      depth += 1;
    } else if (CLOSING_QUOTES.includes(ch)) {
      depth = Math.max(0, depth - 1);
      // 겹친 인용(「『…。』」)은 닫는 괄호 묶음 앞의 글자를 본다.
      let before = i - 1;
      while (before > start && CLOSING_QUOTES.includes(text[before]!)) {
        before -= 1;
      }
      const endsQuotedSentence =
        depth === 0 &&
        quoteOpensSentence &&
        SENTENCE_ENDS.includes(text[before] ?? "");
      if (endsQuotedSentence) {
        const end = skip(text, i + 1, CLOSING_QUOTES);
        push(start, end);
        start = end;
        i = end;
        continue;
      }
    } else if (depth === 0 && SENTENCE_ENDS.includes(ch)) {
      // ！？처럼 이어진 끝 부호와, 바로 뒤의 닫는 괄호까지 이 문장에 붙인다.
      const end = skip(text, skip(text, i + 1, SENTENCE_ENDS), CLOSING_QUOTES);
      push(start, end);
      start = end;
      i = end;
      continue;
    }
    i += 1;
  }
  push(start, text.length);
  return sentences;
}

function skip(text: string, from: number, chars: string): number {
  let index = from;
  while (index < text.length && chars.includes(text[index]!)) index += 1;
  return index;
}
