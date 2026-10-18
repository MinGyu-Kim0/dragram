def analyze(client, text):
    return client.post("/api/analyses/", {"text": text}, content_type="application/json")


def test_new_sentence_returns_translation(client, fake_llm):
    fake_llm.response = {"translation_ko": "나는 학생입니다."}

    response = analyze(client, "私は学生です。")

    assert response.status_code == 200
    assert response.json() == {"translation_ko": "나는 학생입니다."}


def test_llm_receives_sentence_and_token_ids(client, fake_llm):
    analyze(client, "私は学生です。")

    [request] = fake_llm.requests
    assert request["sentence"] == "私は学生です。"
    assert request["tokens"] == [
        {"id": 0, "surface": "私"},
        {"id": 1, "surface": "は"},
        {"id": 2, "surface": "学生"},
        {"id": 3, "surface": "です"},
        {"id": 4, "surface": "。"},
    ]
