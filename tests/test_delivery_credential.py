import json
import tempfile
import unittest
from pathlib import Path

from exchange import Exchange


class DeliveryCredentialTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Exchange(Path(self.temp.name) / "exchange.db")
        svc = self.service
        svc.spatial.register_unit("city", "云州市", "city", "2026-11-01")
        svc.spatial.register_unit("zone-a", "滨湖街区", "block", "2026-11-01", parent_id="city")
        svc.spatial.register_unit("zone-b", "山门外商圈", "district", "2026-11-01", parent_id="city")
        svc.spatial.assert_relation("zone-a", "zone-b", "adjacent", "支付机构",
                                    "2026-11-02", "边界核定，两范围相邻不重叠")
        svc.catalog.register("src-a", "支付机构", "云州市", "restricted",
                             [("amount", "交易金额", "decimal", False)], "2026-11-01")
        svc.catalog.register("src-b", "演艺平台", "云州市", "restricted",
                             [("amount", "交易金额", "decimal", False)], "2026-11-01")
        svc.catalog.ingest("asset-a", "src-a", {"amount": 1200}, "2026-11-03")
        svc.catalog.ingest("asset-b", "src-b", {"amount": 980}, "2026-11-03")
        svc.calibers.define(
            "cal-a", "街区消费", "spending", "支付平台结算额汇总",
            "2026-10-01", "2026-10-31", "day", ["zone-a"],
            "含街区餐饮与零售", "排除景区门票", "支付机构", "2026-11-02", "资料室",
        )
        svc.calibers.define(
            "cal-b", "演出消费", "spending", "会员商户交易归并",
            "2026-10-01", "2026-10-31", "day", ["zone-b"],
            "含演出与周边消费", "排除线上订单", "演艺平台", "2026-11-02", "资料室",
        )
        svc.calibers.bind_asset("asset-a", "cal-a", "2026-11-03", "资料室")
        svc.calibers.bind_asset("asset-b", "cal-b", "2026-11-03", "资料室")
        svc.attribution.issue("lic-a", "src-a", "来源：支付机构交易汇总", False,
                              "仅可表述为街区消费，不得表述为景区自身收入",
                              "2027-12-31", "2026-11-03", "资料室")
        svc.attribution.issue("lic-b", "src-b", "来源：演艺平台交易汇总", True,
                              "引用须注明时间窗与商圈范围",
                              "2027-12-31", "2026-11-03", "资料室")
        for source_id in ("src-a", "src-b"):
            svc.grants.issue(f"g-{source_id}", source_id, "文旅部门", "影响解释",
                             "2027-12-31", "2026-11-03")
            svc.policies.set("云州市", "restricted", "影响解释", "allow", "2026-11-03", "资料室")
        self.revision = svc.products.assemble("impact", "景区外消费汇总",
                                              ["asset-a", "asset-b"], "2026-11-04", "资料室")

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_receipt_carries_coverage_usage_and_lineage(self):
        receipt = self.service.delivery.send(
            "d-1", "impact", self.revision, "文旅部门", "影响解释", "2026-11-05",
        )
        # 覆盖范围：每份原件的口径全文与空间单元
        coverage = receipt["coverage"]
        self.assertEqual(len(coverage), 2)
        by_asset = {item["asset_id"]: item for item in coverage}
        caliber_a = by_asset["asset-a"]["caliber"]
        self.assertEqual(caliber_a["metric"], "街区消费")
        self.assertEqual(caliber_a["scope_units"], ["zone-a"])
        self.assertEqual(caliber_a["window_start"], "2026-10-01")
        # 使用条件：按来源的署名、景区表述边界与授权
        source_terms = {item["source_id"]: item for item in receipt["usage"]["sources"]}
        self.assertFalse(source_terms["src-a"]["attribution"]["scenic_claim_allowed"])
        self.assertTrue(source_terms["src-b"]["attribution"]["scenic_claim_allowed"])
        self.assertIsNotNone(source_terms["src-a"]["grant_id"])
        self.assertTrue(receipt["lineage_digest"])
        # 无阻断项；时间窗等咨询性警告仍随凭据说明
        self.assertFalse(any(item["blocking"] for item in receipt["warnings"]))
        # 快照列以 JSON 原文留存，可直接供外部系统核验
        parsed = json.loads(receipt["coverage_snapshot"])
        self.assertEqual(parsed[0]["caliber"]["id"], "cal-a")

    def test_published_revision_freezes_snapshot_against_later_corrections(self):
        receipt = self.service.delivery.send(
            "d-1", "impact", self.revision, "文旅部门", "影响解释", "2026-11-05",
        )
        self.assertEqual(
            self.service.connection.execute(
                "SELECT state FROM products WHERE id='impact' AND revision=?",
                (self.revision,),
            ).fetchone()["state"],
            "published",
        )
        # 交付后合作方修正口径并发布新版本，历史回执内容不变
        self.service.calibers.define(
            "cal-a", "街区消费（修订）", "spending", "支付平台结算额汇总（含外卖）",
            "2026-10-01", "2026-10-31", "day", ["zone-a"],
            "含街区餐饮、零售与外卖", "排除景区门票", "支付机构", "2026-11-09", "资料室",
        )
        replay = self.service.delivery.send(
            "d-1", "impact", self.revision, "文旅部门", "影响解释", "2026-11-10",
        )
        self.assertEqual(replay, receipt)
        stored = replay["coverage"][0]["caliber"]
        self.assertEqual(stored["metric"], "街区消费")
        self.assertEqual(stored["revision"], 1)
        # 已发布修订不能以新编号再次交付
        with self.assertRaises(ValueError):
            self.service.delivery.send(
                "d-2", "impact", self.revision, "文旅部门", "影响解释", "2026-11-10",
            )

    def test_corrections_after_publish_flow_into_new_revision_with_fresh_review(self):
        self.service.delivery.send("d-1", "impact", self.revision,
                                   "文旅部门", "影响解释", "2026-11-05")
        # 新原件引入与 asset-a 同口径、同范围、同窗口的另一份支付汇总
        self.service.catalog.ingest("asset-a2", "src-a", {"amount": 700}, "2026-11-09")
        self.service.calibers.bind_asset("asset-a2", "cal-a", "2026-11-09", "资料室")
        new_revision = self.service.products.assemble(
            "impact", "景区外消费汇总", ["asset-a", "asset-b", "asset-a2"],
            "2026-11-09", "资料室",
        )
        warnings = self.service.review.assess("impact", new_revision, "2026-11-09", "资料室")
        codes = {item["code"] for item in warnings if item["blocking"]}
        self.assertIn("scope_overlap", codes)
        with self.assertRaises(PermissionError):
            self.service.delivery.send("d-3", "impact", new_revision,
                                       "文旅部门", "影响解释", "2026-11-10")
        # 历史交付仍可凭编号追溯
        history = self.service.history("impact")
        self.assertTrue(any(row["action"] == "delivery.accept" for row in history))


if __name__ == "__main__":
    unittest.main()
