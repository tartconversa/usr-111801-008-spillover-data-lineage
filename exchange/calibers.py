import hashlib
import json

from .audit import write


def caliber_digest(payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class Calibers:
    """版本化汇总口径与原件绑定。修正口径另立新版本，旧版本保留，历史绑定不被改写。"""

    def __init__(self, connection):
        self.connection = connection

    def define(self, caliber_id, metric, metric_category, method, window_start, window_end,
               granularity, scope_units, include_rule, exclude_rule, owner, at, actor):
        if not scope_units:
            raise ValueError("口径缺少地理范围")
        if window_start > window_end:
            raise ValueError("口径时间窗起止无效")
        scope_units = list(dict.fromkeys(scope_units))
        old = self.connection.execute(
            "SELECT revision,status FROM calibers WHERE id=? ORDER BY revision DESC LIMIT 1",
            (caliber_id,),
        ).fetchone()
        revision = old["revision"] + 1 if old else 1
        supersedes = old["revision"] if old else None
        payload = {
            "metric": metric, "metric_category": metric_category, "method": method,
            "window_start": window_start, "window_end": window_end, "granularity": granularity,
            "scope_units": scope_units, "include_rule": include_rule, "exclude_rule": exclude_rule,
            "owner": owner,
        }
        digest = caliber_digest(payload)
        with self.connection:
            if old:
                self.connection.execute(
                    "UPDATE calibers SET status='superseded' WHERE id=? AND revision=?",
                    (caliber_id, old["revision"]),
                )
            self.connection.execute(
                "INSERT INTO calibers(id,revision,metric,metric_category,method,window_start,window_end,"
                "granularity,scope_units,include_rule,exclude_rule,owner,status,supersedes_revision,digest,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'active', ?,?,?)",
                (caliber_id, revision, metric, metric_category, method, window_start, window_end,
                 granularity, json.dumps(scope_units, ensure_ascii=False), include_rule, exclude_rule,
                 owner, supersedes, digest, at),
            )
            write(self.connection, at, actor, "caliber.define", caliber_id,
                  {"revision": revision, "metric": metric, "supersedes": supersedes})
        return revision

    def bind_asset(self, asset_id, caliber_id, at, actor):
        asset = self.connection.execute("SELECT id FROM assets WHERE id=?", (asset_id,)).fetchone()
        if asset is None:
            raise KeyError(asset_id)
        caliber = self.connection.execute(
            "SELECT revision FROM calibers WHERE id=? AND status='active'", (caliber_id,)
        ).fetchone()
        if caliber is None:
            raise ValueError("口径不存在或无有效版本")
        with self.connection:
            self.connection.execute(
                "INSERT INTO asset_calibers(asset_id,caliber_id,caliber_revision,bound_at) VALUES(?,?,?,?) "
                "ON CONFLICT(asset_id) DO UPDATE SET caliber_id=excluded.caliber_id,"
                "caliber_revision=excluded.caliber_revision,bound_at=excluded.bound_at",
                (asset_id, caliber_id, caliber["revision"], at),
            )
            write(self.connection, at, actor, "caliber.bind", asset_id,
                  {"caliber": caliber_id, "revision": caliber["revision"]})
        return caliber["revision"]

    def asset_caliber(self, asset_id):
        row = self.connection.execute(
            "SELECT c.* FROM asset_calibers b JOIN calibers c "
            "ON c.id=b.caliber_id AND c.revision=b.caliber_revision WHERE b.asset_id=?",
            (asset_id,),
        ).fetchone()
        return self._expand(row)

    def get(self, caliber_id, revision):
        row = self.connection.execute(
            "SELECT * FROM calibers WHERE id=? AND revision=?", (caliber_id, revision)
        ).fetchone()
        if row is None:
            raise KeyError((caliber_id, revision))
        return self._expand(row)

    def _expand(self, row):
        if row is None:
            return None
        result = dict(row)
        result["scope_units"] = json.loads(result["scope_units"])
        return result
