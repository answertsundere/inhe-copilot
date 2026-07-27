import pytest

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


@pytest.mark.parametrize(
    "text",
    [
        "卧室使用",
        "浴室使用",
        "客厅摆放",
        "省空间，也省力",
        "防潮吗，怕不怕水",
        "室内和室外都能用吗",
        "房间比较小，会不会占地方",
        "商品材质是PP，尺寸是80厘米，颜色是白色",
        "能不能放浴室",
        "放卧室会不会占地方",
        "放浴室是不是就不怕水",
    ],
)
def test_sanitize_text_preserves_normal_product_and_room_semantics(text):
    assert sanitize_text(text) == text


def test_sanitize_obj_preserves_business_semantics_across_fields():
    payload = {
        "customer_message": "放浴室是不是就不怕水",
        "goal_summary": "放浴室是不是就不怕水",
        "product_title": "客厅卧室浴室收纳凳",
        "category": "家居收纳",
        "attribute_name": "材质",
        "admitted_evidence": {
            "content": "主体材质为PP，宽80厘米，颜色为白色",
        },
    }

    assert sanitize_obj(payload) == payload


@pytest.mark.parametrize(
    "text",
    [
        "收货地址：北京市朝阳区幸福路12号",
        "浙江省杭州市西湖区文三路99号",
        "请送到幸福路12号",
        "地址：上海市浦东新区测试路88号，放卧室门口",
    ],
)
def test_sanitize_text_redacts_concrete_addresses(text):
    projected = sanitize_text(text)

    assert "[ADDRESS_REDACTED]" in projected
    assert "幸福路12号" not in projected
    assert "文三路99号" not in projected
    assert "测试路88号" not in projected


def test_sanitize_text_keeps_existing_non_address_pii_guards():
    projected = sanitize_text(
        "手机号13812345678，账号：buyer-test，token=secret-value"
    )

    assert "13812345678" not in projected
    assert "buyer-test" not in projected
    assert "secret-value" not in projected
