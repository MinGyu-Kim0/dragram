// 내 기록 상세 API(GET /api/my-sentences/<id>/)의 응답. 확장 캐시 응답(analysis 이벤트 + 루비)과
// 같은 모양이다. 칸의 뜻은 extension/utils/api.ts와 같다. 사이드 패널과 공용으로 묶지 않는다(#195).

export type ReviewStatus = "pending" | "approved";

export interface PatternConnection {
  pattern_id: number;
  text: string | null;
  review_status: ReviewStatus | null;
  filled: boolean;
}

export interface Alternative {
  name: string;
  translation_ko: string;
  review_status: ReviewStatus;
}

export interface GrammarItem {
  // 원문 기준 UTF-16 위치 [start, end)
  start: number;
  end: number;
  pattern_name: string;
  connection?: PatternConnection;
  state: "decided" | "divergent" | "unresolved";
  name: string;
  explanation_ko: string | null;
  korean_equivalent: string | null;
  korean_equivalent_review_status: ReviewStatus | null;
  pos_tags: string[];
  function_tags: string[];
  function_tags_review_status: ReviewStatus | null;
  review_status: ReviewStatus;
  register: "standard" | "colloquial";
  variant_of: string | null;
  alternatives?: Alternative[];
  parts?: GrammarItem[];
}

export interface WordSense {
  tags: string[];
  gloss_en: string[];
  origin: "jmdict" | "llm";
  status: ReviewStatus;
  meaning_ko: string | null;
  meaning_status: "ai" | "reviewed" | "failed";
}

export interface WordItem {
  start: number;
  end: number;
  dictionary_form: string;
  reading: string;
  tags: string[];
  in_dictionary: boolean;
  is_name?: boolean;
  reading_ko?: string | null;
  sense: WordSense | null;
}

export interface RubyItem {
  start: number;
  end: number;
  reading: string;
}

export interface NameSpan {
  start: number;
  end: number;
  type: "person" | "place" | "org" | "work" | "other";
}

export interface SentenceDetail {
  id: number;
  text: string;
  analyzed_at: string;
  translation_ko: string;
  ruby: RubyItem[];
  grammar: GrammarItem[];
  words: WordItem[];
  name_spans?: NameSpan[] | null;
}

// 태그 코드의 화면 이름(DESIGN.md 5장, 사이드 패널 tag-names.ts와 같다). 모르는 코드는 보이지 않는다.
export const TAG_NAMES: Record<string, string> = {
  noun: "명사",
  proper_noun: "고유명사",
  pronoun: "대명사",
  verb: "동사",
  group1: "1그룹",
  group1_exception: "예외 1그룹",
  group2: "2그룹",
  group3: "3그룹",
  i_adjective: "い형용사",
  na_adjective: "な형용사",
  adverb: "부사",
  adnominal: "연체사",
  conjunction: "접속사",
  interjection: "감탄사",
  particle: "조사",
  auxiliary_verb: "조동사",
  prefix: "접두사",
  suffix: "접미사",
  transitive: "타동사",
  intransitive: "자동사",
  honorific: "존경어",
  humble: "겸양어",
  polite: "정중어",
  uk: "보통 가나로 씀",
  onomatopoeia: "의성어·의태어",
  loanword: "외래어",
  colloquial: "회화체",
  formal: "문어·격식",
  archaic: "고어",
  dated: "예스러운 말",
  poetic: "시어",
  slang: "속어",
  internet_slang: "인터넷 속어",
  male: "남성어",
  female: "여성어",
  children: "유아어",
  vulgar: "비속어",
  jocular: "농담조",
  derogatory: "비하어",
};

// 기능 태그 코드의 화면 이름(#151, 서버 FunctionTag·사이드 패널 Grammar.tsx와 같다)
export const FUNCTION_TAG_NAMES: Record<string, string> = {
  passive: "수동",
  causative: "사역",
  causative_passive: "사역수동",
  potential: "가능",
  honorific: "존경",
  humble: "겸양",
  past: "과거",
  progressive: "진행",
  perfective: "완료",
  resultative: "결과 상태",
  polite: "정중",
  casual: "회화체",
  negative: "부정",
  conjecture: "추측",
  hearsay: "전문",
  obligation: "당위",
  conditional: "조건",
  cause: "원인·이유",
  adversative: "역접",
  purpose: "목적",
  listing: "나열",
  topic: "주제",
  subject: "주어",
  object: "목적어",
  target: "대상",
  place: "장소",
  time: "시간",
  means: "수단",
  goal: "도달점",
  source: "출발점",
  scope: "범위",
  comparison: "비교",
};

export const NAME_TYPE_NAMES: Record<NameSpan["type"], string> = {
  person: "사람 이름",
  place: "장소 이름",
  org: "조직 이름",
  work: "작품 이름",
  other: "기타 이름",
};
