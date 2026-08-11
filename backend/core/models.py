from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import F, Q


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class User(AbstractUser):
    pass


class Sentence(TimeStampedModel):
    text = models.TextField()
    normalized_text = models.TextField()
    text_hash = models.CharField(max_length=64, unique=True)

    def __str__(self):
        return self.text[:80]


class MorphologicalAnalysis(TimeStampedModel):
    sentence = models.ForeignKey(Sentence, related_name="morphologies", on_delete=models.CASCADE)
    analyzer = models.CharField(max_length=30, default="SudachiPy")
    analyzer_version = models.CharField(max_length=50)
    dictionary_version = models.CharField(max_length=50)
    split_mode = models.CharField(max_length=1, default="C")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sentence", "analyzer_version", "dictionary_version", "split_mode"],
                name="unique_morphology_version",
            )
        ]


class Morpheme(models.Model):
    morphology = models.ForeignKey(MorphologicalAnalysis, related_name="tokens", on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    surface = models.CharField(max_length=255)
    normalized_form = models.CharField(max_length=255, blank=True)
    dictionary_form = models.CharField(max_length=255, blank=True)
    reading_form = models.CharField(max_length=255, blank=True)
    pos1 = models.CharField(max_length=50, blank=True)
    pos2 = models.CharField(max_length=50, blank=True)
    pos3 = models.CharField(max_length=50, blank=True)
    pos4 = models.CharField(max_length=50, blank=True)
    pos5 = models.CharField(max_length=50, blank=True)
    pos6 = models.CharField(max_length=50, blank=True)
    begin_offset = models.PositiveIntegerField()
    end_offset = models.PositiveIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["morphology", "position"], name="unique_morpheme_position"),
            models.CheckConstraint(condition=Q(end_offset__gt=F("begin_offset")), name="morpheme_has_valid_offsets"),
        ]


class Grammar(TimeStampedModel):
    code = models.CharField(max_length=80, unique=True)
    name_ja = models.CharField(max_length=120)
    name_ko = models.CharField(max_length=120)
    summary = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name_ja} ({self.name_ko})"


class SentenceAnalysis(TimeStampedModel):
    sentence = models.ForeignKey(Sentence, related_name="analyses", on_delete=models.CASCADE)
    meaning_ko = models.TextField(blank=True)
    explanation = models.TextField(blank=True)
    model_name = models.CharField(max_length=100)
    raw_result = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sentence", "model_name"], name="unique_sentence_model_analysis")
        ]


class GrammarMatch(models.Model):
    analysis = models.ForeignKey(SentenceAnalysis, related_name="grammar_matches", on_delete=models.CASCADE)
    grammar = models.ForeignKey(Grammar, related_name="sentence_matches", on_delete=models.CASCADE)
    begin_offset = models.PositiveIntegerField()
    end_offset = models.PositiveIntegerField()
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    evidence = models.TextField(blank=True)

    class Meta:
        ordering = ["begin_offset"]
        constraints = [
            models.CheckConstraint(condition=Q(end_offset__gt=F("begin_offset")), name="grammar_match_has_valid_offsets")
        ]


class UserSentence(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="saved_sentences", on_delete=models.CASCADE)
    sentence = models.ForeignKey(Sentence, related_name="saved_by", on_delete=models.CASCADE)
    source_url = models.URLField(max_length=2000, blank=True)
    source_title = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "sentence"], name="unique_user_sentence")]
