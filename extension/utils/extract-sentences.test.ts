import { beforeEach, expect, test } from "vitest";
import { extractSentences } from "./extract-sentences";

beforeEach(() => {
  document.body.innerHTML = "";
});

// 본문을 그리고, 화면에 보이는 글자 기준으로 from부터 to 앞까지를 고른 범위를 만든다.
function select(html: string, from: string, to: string): Range {
  document.body.innerHTML = html;
  return rangeBetween(from, to);
}

function rangeBetween(from: string, to: string): Range {
  const range = document.createRange();
  const [startNode, startOffset] = locate(from, "start");
  const [endNode, endOffset] = locate(to, "end");
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);
  return range;
}

// 글자열이 처음 나오는 텍스트 노드와 위치. start는 그 글자열의 시작, end는 끝.
function locate(text: string, edge: "start" | "end"): [Text, number] {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const index = node.textContent!.indexOf(text);
    if (index !== -1) {
      return [node as Text, edge === "start" ? index : index + text.length];
    }
  }
  throw new Error(`본문에 없는 글자: ${text}`);
}

test("문장 일부를 고르면 문장 전체와 그 안의 드래그 범위를 돌려준다", () => {
  const range = select("<p>私は学生です。猫が好きです。</p>", "学生", "学生");

  expect(extractSentences(range)).toEqual([
    { text: "私は学生です。", selection: { start: 2, end: 4 } },
  ]);
});

test("여러 문장에 걸쳐 고르면 문장별로 나누고, 드래그 범위도 문장마다 잘라 준다", () => {
  const range = select("<p>私は学生です。猫が好きです。</p>", "学生", "猫");

  expect(extractSentences(range)).toEqual([
    { text: "私は学生です。", selection: { start: 2, end: 7 } },
    { text: "猫が好きです。", selection: { start: 0, end: 1 } },
  ]);
});

test("인용부호 안의 마침표에서는 나누지 않는다", () => {
  const range = select(
    "<p>彼は「行く。待って。」と言った。次だ。</p>",
    "言っ",
    "言っ",
  );

  expect(extractSentences(range)).toEqual([
    {
      text: "彼は「行く。待って。」と言った。",
      selection: { start: 12, end: 14 },
    },
  ]);
});

test("끝 부호 바로 뒤의 닫는 괄호는 앞 문장에 붙인다", () => {
  const range = select("<p>「行く。」次だ。</p>", "行く", "次");

  expect(extractSentences(range).map((sentence) => sentence.text)).toEqual([
    "「行く。」",
    "次だ。",
  ]);
});

test("！？가 이어지면 한 문장 끝으로 본다", () => {
  const range = select("<p>本当？！そうだ。</p>", "本当", "本当");

  expect(extractSentences(range).map((sentence) => sentence.text)).toEqual([
    "本当？！",
  ]);
});

test("블록 경계에서 멈춘다", () => {
  const range = select(
    "<div><p>前の段落</p><p>次の段落です</p></div>",
    "段落です",
    "段落です",
  );

  expect(extractSentences(range)).toEqual([
    { text: "次の段落です", selection: { start: 2, end: 6 } },
  ]);
});

test("줄바꿈(<br>)에서 멈춘다", () => {
  const range = select("<p>一行目<br>二行目</p>", "二", "二");

  expect(extractSentences(range).map((sentence) => sentence.text)).toEqual([
    "二行目",
  ]);
});

test("화면에 줄바꿈으로 보이는 개행에서 멈추고, 공백으로 보이는 개행에서는 멈추지 않는다", () => {
  const preLine = select(
    '<div style="white-space: pre-line">一行目\n二行目</div>',
    "二",
    "二",
  );
  expect(extractSentences(preLine).map((sentence) => sentence.text)).toEqual([
    "二行目",
  ]);

  const normal = select("<div>一行目\n二行目</div>", "二", "二");
  expect(extractSentences(normal).map((sentence) => sentence.text)).toEqual([
    "一行目 二行目",
  ]);
});

test("루비의 읽기 글자(rt·rp)는 빼고 본문만 남긴다", () => {
  const range = select(
    "<p>私は<ruby>漢字<rp>(</rp><rt>かんじ</rt><rp>)</rp></ruby>が好き。</p>",
    "漢字",
    "漢字",
  );

  expect(extractSentences(range)).toEqual([
    { text: "私は漢字が好き。", selection: { start: 2, end: 4 } },
  ]);
});

test("문장 안의 인라인 요소는 이어서 한 문장으로 본다", () => {
  const range = select("<p>私は<b>学生</b>です。</p>", "学生", "学生");

  expect(extractSentences(range).map((sentence) => sentence.text)).toEqual([
    "私は学生です。",
  ]);
});

test("문장이 몇 개든 모두 돌려준다", () => {
  const range = select("<p>一。二。三。四。</p>", "一", "四");

  expect(extractSentences(range).map((sentence) => sentence.text)).toEqual([
    "一。",
    "二。",
    "三。",
    "四。",
  ]);
});

test("문장 앞뒤 공백은 빼고, 드래그 범위도 그 기준으로 맞춘다", () => {
  // 반각 공백과 전각 공백(U+3000)
  const range = select(
    "<p> \u3000私は学生です。  猫です。</p>",
    "学生",
    "学生",
  );

  expect(extractSentences(range)).toEqual([
    { text: "私は学生です。", selection: { start: 2, end: 4 } },
  ]);
});

test("인용이 겹친 대사(「『…。』」)도 닫는 괄호 묶음 뒤에서 문장을 끝낸다", () => {
  const range = select("<p>「『行く。』」次だ。</p>", "行く", "次");

  expect(extractSentences(range).map((sentence) => sentence.text)).toEqual([
    "「『行く。』」",
    "次だ。",
  ]);
});

test("visibility로 숨긴 글자는 빼고, 그 안에서 다시 보이게 한 글자는 남긴다", () => {
  const range = select(
    '<p>今日は<span style="visibility: hidden">秘密。<b style="visibility: visible">本当に</b></span>晴れです。</p>',
    "晴れ",
    "晴れ",
  );

  expect(extractSentences(range)).toEqual([
    { text: "今日は本当に晴れです。", selection: { start: 6, end: 8 } },
  ]);
});
