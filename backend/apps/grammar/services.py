import hashlib

from core.models import Grammar


def get_or_create_grammar(canonical_name, name_ko, summary):
    code = f"llm-{hashlib.sha256(canonical_name.encode('utf-8')).hexdigest()[:24]}"
    grammar, _ = Grammar.objects.get_or_create(
        code=code,
        defaults={"name_ja": canonical_name, "name_ko": name_ko, "summary": summary},
    )
    return grammar
