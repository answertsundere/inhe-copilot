from app.main import create_app


def test_cleaning_and_material_safety_use_different_replies():
    app = create_app()
    client = app.test_client()
    product_name = "\u82f1\u79be\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67b6\u6574\u7406\u5ba2\u5385\u96f6\u98df\u684c\u9762\u513f\u7ae5\u73a9\u5177\u5367\u5ba4\u53ef\u62fc\u642d\u50a8\u7269\u62bd\u5c49"

    cleaning = client.post("/ask/api/analyze", json={
        "message": "\u8fd9\u4e2a\u810f\u4e86\u600e\u4e48\u6e05\u6d01\uff1f\u53ef\u4ee5\u6c34\u6d17\u5417\uff1f",
        "conversation_id": "test_cleaning_care",
        "product_name": product_name,
    }).get_json()
    material = client.post("/ask/api/analyze", json={
        "message": "\u8fd9\u4e2a\u6750\u8d28\u5b89\u5168\u5417\uff1f\u4f1a\u4e0d\u4f1a\u5bb9\u6613\u53d7\u6f6e\uff1f",
        "conversation_id": "test_material_safety",
        "product_name": product_name,
    }).get_json()

    assert cleaning["intent"] == "cleaning_care"
    assert material["intent"] == "material_safety"
    assert cleaning["suggested_reply"] != material["suggested_reply"]
    assert "\u6574\u4f53\u6c34\u6d17" in cleaning["suggested_reply"]
    assert "\u6750\u8d28" in material["suggested_reply"]
    assert material["requires_human_review"] is True
