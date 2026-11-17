import tempfile
import unittest
from pathlib import Path

from exchange import Exchange


class GovernanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Exchange(Path(self.temp.name) / "exchange.db")
        svc = self.service
        svc.spatial.register_unit("city", "云州市", "city", "2026-11-01")
        svc.spatial.register_unit("zone-a", "滨湖街区", "block", "2026-11-01", parent_id="city")
        svc.spatial.register_unit("zone-b", "山门外商圈", "district", "2026-11-01", parent_id="city")
        # 合作方最初主张两个范围重叠
        self.relation_id = svc.spatial.assert_relation(
            "zone-a", "zone-b", "overlaps", "支付机构", "2026-11-02", "初版归属，边界未核定",
        )
        svc.catalog.register("src-a", "支付机构", "云州市", "restricted",
                             [("amount", "交易金额", "decimal", False)], "2026-11-01")
        svc.catalog.register("src-b", "演艺平台", "云州市", "restricted",
                             [("amount", "交易金额", "decimal", False)], "2026-11-01")
        svc.catalog.ingest("asset-a", "src-a", {"amount": 1200}, "2026-11-03")
        svc.catalog.ingest("asset-b", "src-b", {"amount": 980}, "2026-11-03")
        svc.calibers.define(
            "cal-a", "景区带动收入", "spending", "支付平台结算额汇总",
            "2026-10-01", "2026-10-31", "day", ["zone-a"],
            "含街区餐饮与零售", "排除景区门票", "支付机构", "2026-11-02", "资料室",
        )
        svc.calibers.define(
            "cal-b", "景区带动收入", "spending", "会员商户交易归并",
            "2026-09-15", "2026-10-15", "day", ["zone-b"],
            "含演出与周边消费", "排除线上订单", "演艺平台", "2026-11-02", "资料室",
        )
        svc.calibers.bind_asset("asset-a", "cal-a", "2026-11-03", "资料室")
        svc.calibers.bind_asset("asset-b", "cal-b", "2026-11-03", "资料室")
        svc.attribution.issue("lic-a", "src-a", "来源：支付机构交易汇总", False,
                              "仅可表述为街区消费，不得表述为景区自身收入",
                              "2027-12-31", "2026-11-03", "资料室")
        svc.attribution.issue("lic-b", "src-b", "来源：演艺平台交易汇总", False,
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

    def _codes(self, warnings):
        return {item["code"]: item for item in warnings}

    def _blocking(self, warnings):
        return {item["code"] for item in warnings if item["blocking"]}

    def test_overlapping_scopes_and_same_name_caliber_block_merge(self):
        warnings = self.service.review.assess("impact", self.revision, "2026-11-04", "资料室")
        blocking = self._blocking(warnings)
        self.assertIn("scope_overlap", blocking)
        self.assertIn("caliber_mismatch", blocking)
        codes = self._codes(warnings)
        self.assertIn("window_mismatch", codes)
        self.assertFalse(codes["window_mismatch"]["blocking"])
        # 同名指标不可直接相加的原因写入警告细节
        mismatch = codes["caliber_mismatch"]["detail"]
        self.assertEqual(mismatch["metric"], "景区带动收入")
        self.assertEqual(len(mismatch["calibers"]), 2)
        # 归属许可不允许表述为景区自身收入，作为使用条件警告保留
        scenic = {item["subject"]: item for item in warnings
                  if item["code"] == "scenic_claim_restricted"}
        self.assertFalse(scenic["src-a"]["blocking"])
        self.assertEqual(scenic["src-a"]["subject"], "src-a")
        self.assertIn("src-b", scenic)

    def test_delivery_blocked_until_unmergeable_points_cleared(self):
        with self.assertRaises(PermissionError) as caught:
            self.service.delivery.send("d-1", "impact", self.revision, "文旅部门",
                                       "影响解释", "2026-11-05")
        reasons = {item["reason"] for item in caught.exception.args[0]}
        self.assertIn("scope_overlap", reasons)
        self.assertIn("caliber_mismatch", reasons)

    def test_partner_spatial_correction_clears_overlap_but_keeps_history(self):
        new_id = self.service.spatial.correct_relation(
            self.relation_id, "zone-a", "zone-b", "adjacent", "支付机构",
            "2026-11-06", "边界核定后两范围相邻不重叠",
        )
        self.assertEqual(self.service.spatial.get_relation(self.relation_id)["status"], "superseded")
        self.assertEqual(self.service.spatial.get_relation(new_id)["status"], "active")
        self.assertFalse(self.service.spatial.scopes_overlap("zone-a", "zone-b"))
        warnings = self.service.review.assess("impact", self.revision, "2026-11-06", "资料室")
        self.assertNotIn("scope_overlap", self._blocking(warnings))
        # 同名异义口径仍不可合并，时间窗咨询性警告仍在
        self.assertIn("caliber_mismatch", self._blocking(warnings))
        self.assertIn("window_mismatch", self._codes(warnings))
        # 修正动作进入审计血缘
        actions = [row["action"] for row in self.service.history(str(new_id))]
        self.assertIn("spatial.relation_correct", actions)

    def test_caliber_revision_creates_new_version_without_rewinding_binding(self):
        self.service.calibers.define(
            "cal-a", "街区消费", "spending", "支付平台结算额汇总",
            "2026-10-01", "2026-10-31", "day", ["zone-a"],
            "含街区餐饮与零售", "排除景区门票", "支付机构", "2026-11-07", "资料室",
        )
        old = self.service.calibers.get("cal-a", 1)
        new = self.service.calibers.get("cal-a", 2)
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(new["status"], "active")
        # 历史绑定仍指向修订时的口径版本
        self.assertEqual(self.service.calibers.asset_caliber("asset-a")["revision"], 1)
        self.service.calibers.bind_asset("asset-a", "cal-a", "2026-11-07", "资料室")
        self.assertEqual(self.service.calibers.asset_caliber("asset-a")["revision"], 2)

    def test_missing_caliber_binding_and_missing_license_are_blocking(self):
        self.service.catalog.ingest("asset-c", "src-a", {"amount": 300}, "2026-11-08")
        revision = self.service.products.assemble("partial", "缺口径汇总",
                                                  ["asset-a", "asset-c"], "2026-11-08", "资料室")
        warnings = self.service.review.assess("partial", revision, "2026-11-08", "资料室")
        blocking = self._codes(warnings)
        self.assertTrue(blocking["caliber_missing"]["blocking"])
        self.assertEqual(blocking["caliber_missing"]["subject"], "asset-c")

        self.service.calibers.bind_asset("asset-c", "cal-a", "2026-11-08", "资料室")
        with self.service.connection:
            self.service.connection.execute(
                "UPDATE attribution_licenses SET status='superseded' WHERE source_id='src-a'"
            )
        warnings = self.service.review.assess("partial", revision, "2026-11-08", "资料室")
        self.assertIn("attribution_missing", self._blocking(warnings))

    def test_hierarchical_scope_containment_counts_as_overlap(self):
        self.assertTrue(self.service.spatial.scopes_overlap("city", "zone-a"))
        self.assertTrue(self.service.spatial.scopes_overlap("zone-a", "city"))
        self.assertTrue(self.service.spatial.scopes_overlap("zone-a", "zone-a"))

    def test_expired_license_has_no_effect(self):
        self.service.attribution.issue("lic-c", "src-a", "来源：支付机构", True,
                                       "限期使用", "2026-10-01", "2026-11-09", "资料室")
        self.assertIsNone(self.service.attribution.active_for("src-a", "2026-11-10"))


if __name__ == "__main__":
    unittest.main()
