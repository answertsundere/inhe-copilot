from __future__ import annotations

from app.models.kb_tables import KBMediaAsset


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.committed = False

    def query(self, model):
        return _Query(self.rows)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def test_backfill_media_roles_dry_run_does_not_write():
    from scripts.backfill_media_roles import run

    asset = KBMediaAsset(id=1, asset_type="other", asset_title="\u5b89\u88c5\u56fe\u6b65\u9aa4\u8bf4\u660e")
    db = _Db([asset])

    result = run(apply=False, db_factory=lambda: db)

    assert result["dry_run"] is True
    assert result["would_change_count"] == 1
    assert result["changed_count"] == 0
    assert asset.asset_type == "other"
    assert db.committed is False


def test_backfill_media_roles_apply_updates_only_high_confidence_unknown():
    from scripts.backfill_media_roles import run

    install = KBMediaAsset(id=1, asset_type="other", asset_title="\u5b89\u88c5\u56fe\u6b65\u9aa4\u8bf4\u660e")
    product = KBMediaAsset(id=2, asset_type="sku_image", asset_title="\u5546\u54c1\u4e3b\u56fe")
    db = _Db([install, product])

    result = run(apply=True, db_factory=lambda: db)

    assert result["changed_count"] == 1
    assert install.asset_type == "install_image"
    assert product.asset_type == "sku_image"
    assert db.committed is True
