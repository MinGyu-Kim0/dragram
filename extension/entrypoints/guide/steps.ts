import type { ResultTab } from "../sidepanel/Sentence";

// 가이드(#370)의 한 단계. target은 장면 안에서 강조할 요소의 선택자다. 실제 패널 컴포넌트의
// 클래스를 가리키므로 화면이 바뀌면 함께 고친다(가이드 테스트가 대상이 있는지 본다).
export interface Step {
  title: string;
  body: string;
  target: string;
  // 장면 패널에 보일 탭. 없으면 문법 탭이다.
  tab?: ResultTab;
  // 웹페이지 위에 우클릭 메뉴를 띄운다.
  menu?: boolean;
  // 원문에서 이 위치의 글자를 고른 장면('선택한 카드'가 열린다)
  selected?: number;
}

export const STEPS: Step[] = [
  {
    title: "문장을 골라 분석하기",
    body: "웹페이지의 일본어 문장을 드래그하고 마우스 오른쪽 버튼을 눌러 'Dragram으로 분석'을 고르세요. 오른쪽 사이드 패널에 결과가 나와요.",
    target: '[data-guide="menu-analyze"]',
    menu: true,
  },
  {
    title: "원문",
    body: "고른 문장이에요. 칠해진 부분이 문법이에요.",
    target: ".sentence-card .original",
  },
  {
    title: "선택한 카드",
    body: "원문의 칠해진 부분을 누르면 그 부분의 문법 카드와 단어를 원문 아래에 모아 보여 줘요. 다시 누르거나 '닫기'로 닫아요.",
    target: ".selected-card",
    selected: 13,
  },
  {
    title: "후리가나",
    body: "한자 위 읽기를 켜고 꺼요.",
    target: ".display-toggles > button",
  },
  {
    title: "형광펜 · 밑줄",
    body: "문법 구간을 칠할지 밑줄로 보일지 골라요. 고른 값은 기억돼요.",
    target: ".style-choice",
  },
  {
    title: "번역",
    body: "AI가 옮긴 한국어 번역이에요.",
    target: ".sentence-card .translation",
  },
  {
    title: "문법 · 단어 탭",
    body: "이 문장의 문법 카드와 단어를 나눠 보여 줘요. 숫자는 카드 수예요.",
    target: ".tabs",
  },
  {
    title: "AI 생성·미검수",
    body: "AI가 만들었고 아직 사람이 확인하지 않은 설명이에요. 틀릴 수 있어요. 배지가 없으면 사람이 확인했거나 사전(JMdict)에서 온 내용이에요.",
    target: ".grammar-card .badge-warn",
  },
  {
    title: "다른 해석",
    body: "한 구간이 두 가지로 읽힐 수 있다는 뜻이에요. 위가 더 그럴듯한 해석이고, 이 줄은 다른 해석으로 옮긴 문장이에요.",
    target: ".alternatives",
  },
  {
    title: "추가 · 예문 저장 · 숨김",
    body: "'추가'하면 내 일본어에 들어가고, '✓ 추가됨'을 다시 누르면 제외해요(저장한 예문도 지워져요). '예문 저장'은 이 문장을 예문으로 남기고, '숨김'은 이 패널에서만 카드를 접어 둬요.",
    target: ".grammar-card:nth-child(2) .item-actions",
  },
  {
    title: "단어와 이름 지정",
    body: "사전형·읽기·이 문장에서 고른 뜻이에요. 사람·땅 이름이 뜻으로 풀렸으면 '이름으로 지정'으로 읽기를 정해 두세요. 내 화면에만 적용돼요.",
    target: ".word-list .name-actions",
    tab: "words",
  },
  {
    title: "숨긴 카드",
    body: "숨긴 카드는 탭 맨 아래에 모여요. 펼쳐서 '복원'하면 숨기기 전으로 돌아와요.",
    target: ".hidden-cards",
    tab: "words",
  },
  {
    title: "내 일본어는 웹에서",
    body: "로고를 누르면 웹이 열려요. 추가한 내 일본어와 예문, 학습 카드는 웹에서 봐요.",
    target: ".fake-panel .logo",
  },
];
