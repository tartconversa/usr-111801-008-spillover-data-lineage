import json

from .audit import write
from .attribution import AttributionLicenses
from .calibers import Calibers
from .products import Products
from .spatial import SpatialRegistry


# blocking=1 的警告代表未发布汇总中不可直接合并之处，交付前必须消除
BLOCKING = 1
ADVISORY = 0


class MergeReview:
    """对未发布产品修订做口径、空间与归属评审。

    评审结论写入 product_warnings：blocking 警告不消除则不可交付；
    advisory 警告不阻断交付，但随交付凭据快照对外说明覆盖范围与使用条件。
    """

    def __init__(self, connection):
        self.connection = connection
        self.calibers = Calibers(connection)
        self.spatial = SpatialRegistry(connection)
        self.licenses = AttributionLicenses(connection)
        self.products = Products(connection)

    def assess(self, product_id, revision, at, actor):
        if self.connection.execute(
            "SELECT 1 FROM products WHERE id=? AND revision=?", (product_id, revision)
        ).fetchone() is None:
            raise KeyError((product_id, revision))
        inputs = self.products.inputs(product_id, revision)
        warnings = {}

        def add(code, blocking, subject, detail):
            warnings[(code, subject)] = {
                "code": code, "blocking": bool(blocking), "subject": subject, "detail": detail,
            }

        bound = {}
        for asset in inputs:
            caliber = self.calibers.asset_caliber(asset["id"])
            if caliber is None:
                add("caliber_missing", BLOCKING, asset["id"],
                    {"source": asset["source_id"], "reason": "原件未绑定汇总口径，无法说明覆盖范围"})
            else:
                bound[asset["id"]] = (asset, caliber)

        for source_id in sorted({asset["source_id"] for asset in inputs}):
            license_row = self.licenses.active_for(source_id, at)
            if license_row is None:
                add("attribution_missing", BLOCKING, source_id,
                    {"reason": "来源缺少有效归属许可，对外引用条件不明"})
            elif not license_row["scenic_claim_allowed"]:
                add("scenic_claim_restricted", ADVISORY, source_id,
                    {"citation_term": license_row["citation_term"],
                     "usage_condition": license_row["usage_condition"],
                     "reason": "许可不允许将该来源消费表述为景区自身收入"})

        items = list(bound.items())
        for index, (asset_a, (row_a, caliber_a)) in enumerate(items):
            for asset_b, (row_b, caliber_b) in items[index + 1:]:
                pair = "|".join(sorted((asset_a, asset_b)))
                scope_overlap = self._scopes_overlap(caliber_a["scope_units"], caliber_b["scope_units"])
                window_overlap = not (
                    caliber_a["window_end"] < caliber_b["window_start"]
                    or caliber_b["window_end"] < caliber_a["window_start"]
                )
                same_metric_name = caliber_a["metric"] == caliber_b["metric"]
                same_category = caliber_a["metric_category"] == caliber_b["metric_category"]
                if same_metric_name and self._definition_differs(caliber_a, caliber_b):
                    add("caliber_mismatch", BLOCKING, pair, {
                        "metric": caliber_a["metric"],
                        "calibers": [
                            {"asset": asset_a, "caliber": caliber_a["id"], "revision": caliber_a["revision"]},
                            {"asset": asset_b, "caliber": caliber_b["id"], "revision": caliber_b["revision"]},
                        ],
                        "reason": "同名指标的汇总方式或纳入排除规则不同，直接相加会混淆口径",
                    })
                if scope_overlap and window_overlap and same_category:
                    add("scope_overlap", BLOCKING, pair, {
                        "metric_category": caliber_a["metric_category"],
                        "scopes": [caliber_a["scope_units"], caliber_b["scope_units"]],
                        "windows": [
                            [caliber_a["window_start"], caliber_a["window_end"]],
                            [caliber_b["window_start"], caliber_b["window_end"]],
                        ],
                        "reason": "地理范围与时间窗重叠且属同类指标，直接相加将重复计算",
                    })
                if (caliber_a["window_start"], caliber_a["window_end"]) != (
                    caliber_b["window_start"], caliber_b["window_end"]
                ):
                    add("window_mismatch", ADVISORY, pair, {
                        "windows": [
                            [caliber_a["window_start"], caliber_a["window_end"]],
                            [caliber_b["window_start"], caliber_b["window_end"]],
                        ],
                        "reason": "来源时间窗不一致，引用时须分别注明覆盖期间",
                    })

        ordered = [warnings[key] for key in sorted(warnings)]
        with self.connection:
            self.connection.execute(
                "DELETE FROM product_warnings WHERE product_id=? AND product_revision=?",
                (product_id, revision),
            )
            self.connection.executemany(
                "INSERT INTO product_warnings(product_id,product_revision,code,blocking,subject,detail)"
                " VALUES(?,?,?,?,?,?)",
                [(product_id, revision, item["code"], int(item["blocking"]),
                  item["subject"], json.dumps(item["detail"], ensure_ascii=False, sort_keys=True))
                 for item in ordered],
            )
            write(self.connection, at, actor, "product.review", product_id,
                  {"revision": revision, "warnings": [item["code"] for item in ordered]})
        return ordered

    def warnings_for(self, product_id, revision):
        rows = self.connection.execute(
            "SELECT code,blocking,subject,detail FROM product_warnings "
            "WHERE product_id=? AND product_revision=? ORDER BY code,subject",
            (product_id, revision),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["blocking"] = bool(item["blocking"])
            item["detail"] = json.loads(item["detail"])
            result.append(item)
        return result

    def _scopes_overlap(self, units_a, units_b):
        for unit_a in units_a:
            for unit_b in units_b:
                if self.spatial.scopes_overlap(unit_a, unit_b):
                    return True
        return False

    @staticmethod
    def _definition_differs(caliber_a, caliber_b):
        keys = ("method", "include_rule", "exclude_rule", "granularity")
        return any(caliber_a[key] != caliber_b[key] for key in keys)
