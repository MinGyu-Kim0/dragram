// 내 일본어 API(/api/my-japanese/*)가 쓰는 모양. 칸의 뜻은 extension/utils/api.ts와 같다. 사이드
// 패널과 공용으로 묶지 않는다(#195).

export type ReviewStatus = "pending" | "approved";

export interface WordSense {
  tags: string[];
  gloss_en: string[];
  origin: "jmdict" | "llm";
  status: ReviewStatus;
  meaning_ko: string | null;
  meaning_status: "ai" | "reviewed" | "failed";
}

// 단어 항목(분석 보기의 단어 항목에서 위치를 뺀 모양)
export interface WordEntry {
  dictionary_form: string;
  reading: string;
  tags: string[];
  in_dictionary: boolean;
  sense: WordSense | null;
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
