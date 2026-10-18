from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from analysis import llm
from analysis.morphology import tokenize


# 테스트 단계라 로그인 없이 연다. 로그인 없는 사용을 정식으로 허용한다는 결정은 아니다(#10).
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def analyze(request):
    sentence = request.data["text"]
    result = llm.get_client().analyze(sentence, tokenize(sentence))
    return Response({"translation_ko": result["translation_ko"]})
