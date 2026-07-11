from __future__ import annotations

from types import SimpleNamespace


def test_provider_diagnosis_keeps_transport_report_free_of_secrets_and_raw_content(monkeypatch):
    from scripts import diagnose_product_media_vlm_provider as script

    asset = SimpleNamespace(id=7, i_id="INTERNAL-IDENTITY", asset_url="https://secret.example.test/media?signature=secret")
    guard = SimpleNamespace(enabled=True, write_attempt_count=0, enable=lambda: None, close=lambda: None)
    monkeypatch.setattr(script, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(script, "ReadOnlyDatabaseGuard", lambda _db: guard)
    monkeypatch.setattr(script, "_formal_kb_state_fingerprint", lambda _db: "unchanged")
    monkeypatch.setattr(script, "_current_approved_media_query", lambda _db, _role: SimpleNamespace(limit=lambda _limit: SimpleNamespace(all=lambda: [asset])))
    monkeypatch.setattr(script, "media_asset_eligibility", lambda _asset: [])
    monkeypatch.setattr(script, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    monkeypatch.setattr(script, "vlm_configuration_status", lambda: {
        "enabled": True,
        "api_base_configured": True,
        "api_key_configured": True,
        "model_configured": True,
    })
    monkeypatch.setattr(script, "probe_product_media_vlm", lambda *_args, request_variant, **_kwargs: {
        "request_variant": request_variant,
        "content_present": True,
        "content_length": 12,
        "content_sha256": "hashed-content",
        "schema_parse_success": True,
    })

    result = script.diagnose(media_role="size_image", limit=1, timeout_seconds=1)
    serialized = str(result)

    assert len(result["attempts"]) == 3
    assert result["media_read_success"] is True
    assert result["formal_kb_state_unchanged"] is True
    assert "secret.example" not in serialized
    assert "signature=secret" not in serialized
    assert "INTERNAL-IDENTITY" not in serialized
    assert "b'image'" not in serialized
