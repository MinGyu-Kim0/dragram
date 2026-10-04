from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.services import local_user
from apps.analysis.serializers import serialize_analysis
from core.models import UserSentence


@api_view(["GET"])
@permission_classes([AllowAny])
def list_sentences(request):
    saved_sentences = UserSentence.objects.filter(user=local_user()).select_related("sentence").prefetch_related(
        "sentence__morphologies__tokens",
        "sentence__analyses__grammar_matches__grammar",
    )
    results = []
    for saved in saved_sentences.order_by("-updated_at"):
        analysis = max(saved.sentence.analyses.all(), key=lambda item: item.updated_at, default=None)
        if analysis:
            results.append(serialize_analysis(saved, analysis))
    return Response({"sentences": results})
