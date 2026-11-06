"""구조화 출력 조각을 칸이 닫히는 대로 꺼내는 파서."""

import pytest

from analysis.llm_stream import SectionParser
from errors import AnalysisError, BusinessError


def test_closed_section_comes_out_with_its_value():
    parser = SectionParser()

    assert parser.feed('{"translation_ko": "번역"') == [("translation_ko", "번역")]


def test_unfinished_string_is_available_as_partial_until_it_closes():
    parser = SectionParser()
    parser.feed('{"translation_ko": "앞부')

    assert parser.partial("translation_ko") == "앞부"
    assert parser.partial("spans") is None


def test_whole_response_is_the_parsed_json():
    parser = SectionParser()
    parser.feed('{"spans": []}')

    assert parser.result() == {"spans": []}


def test_cut_off_response_fails_the_analysis():
    parser = SectionParser()
    parser.feed('{"spans": [')

    with pytest.raises(BusinessError) as error:
        parser.result()

    assert error.value.error_code == AnalysisError.FAILED
