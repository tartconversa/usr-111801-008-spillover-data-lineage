import argparse
import json

from .service import Exchange


def main():
    parser = argparse.ArgumentParser(description="景区外消费口径归属本地演练")
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    service = Exchange(args.database)
    try:
        # 1. 空间单元与初始归属关系（合作方初版，边界未核定）
        service.spatial.register_unit("city", "云州市", "city", "2026-11-01")
        service.spatial.register_unit("zone-a", "滨湖街区", "block", "2026-11-01", parent_id="city")
        service.spatial.register_unit("zone-b", "山门外商圈", "district", "2026-11-01", parent_id="city")
        relation_id = service.spatial.assert_relation(
            "zone-a", "zone-b", "overlaps", "支付机构", "2026-11-02", "初版归属，边界未核定",
        )

        # 2. 两家合作机构的交易汇总原件，各自声明口径
        service.catalog.register("src-a", "支付机构", "云州市", "restricted",
                                 [("amount", "交易金额", "decimal", False)], "2026-11-01")
        service.catalog.register("src-b", "演艺平台", "云州市", "restricted",
                                 [("amount", "交易金额", "decimal", False)], "2026-11-01")
        service.catalog.ingest("asset-a", "src-a", {"amount": 1200}, "2026-11-03")
        service.catalog.ingest("asset-b", "src-b", {"amount": 980}, "2026-11-03")
        service.calibers.define(
            "cal-a", "景区带动收入", "spending", "支付平台结算额汇总",
            "2026-10-01", "2026-10-31", "day", ["zone-a"],
            "含街区餐饮与零售", "排除景区门票", "支付机构", "2026-11-02", "资料室",
        )
        service.calibers.define(
            "cal-b", "景区带动收入", "spending", "会员商户交易归并",
            "2026-09-15", "2026-10-15", "day", ["zone-b"],
            "含演出与周边消费", "排除线上订单", "演艺平台", "2026-11-02", "资料室",
        )
        service.calibers.bind_asset("asset-a", "cal-a", "2026-11-03", "资料室")
        service.calibers.bind_asset("asset-b", "cal-b", "2026-11-03", "资料室")
        service.attribution.issue("lic-a", "src-a", "来源：支付机构交易汇总", False,
                                  "仅可表述为街区消费，不得表述为景区自身收入",
                                  "2027-12-31", "2026-11-03", "资料室")
        service.attribution.issue("lic-b", "src-b", "来源：演艺平台交易汇总", False,
                                  "引用须注明时间窗与商圈范围", "2027-12-31",
                                  "2026-11-03", "资料室")
        for source_id in ("src-a", "src-b"):
            service.grants.issue(f"g-{source_id}", source_id, "文旅部门", "影响解释",
                                 "2027-12-31", "2026-11-03")
            service.policies.set("云州市", "restricted", "影响解释", "allow",
                                 "2026-11-03", "资料室")
        revision = service.products.assemble(
            "impact", "景区外消费汇总", ["asset-a", "asset-b"], "2026-11-04", "资料室",
        )

        # 3. 评审标出不可合并之处，交付被阻断
        warnings = service.review.assess("impact", revision, "2026-11-04", "资料室")
        print("初次评审警告：", json.dumps(warnings, ensure_ascii=False, sort_keys=True))
        try:
            service.delivery.send("d-blocked", "impact", revision,
                                  "文旅部门", "影响解释", "2026-11-05")
        except PermissionError as error:
            print("交付阻断原因：", json.dumps(error.args[0], ensure_ascii=False))

        # 4. 合作方修正空间归属（旧关系封存），口径同名异义另出版本并改回差异化指标名
        service.spatial.correct_relation(
            relation_id, "zone-a", "zone-b", "adjacent", "支付机构",
            "2026-11-06", "边界核定后两范围相邻不重叠",
        )
        service.calibers.define(
            "cal-a", "街区消费", "spending", "支付平台结算额汇总",
            "2026-10-01", "2026-10-31", "day", ["zone-a"],
            "含街区餐饮与零售", "排除景区门票", "支付机构", "2026-11-06", "资料室",
        )
        service.calibers.define(
            "cal-b", "演出消费", "spending", "会员商户交易归并",
            "2026-10-01", "2026-10-31", "day", ["zone-b"],
            "含演出与周边消费", "排除线上订单", "演艺平台", "2026-11-06", "资料室",
        )
        service.calibers.bind_asset("asset-a", "cal-a", "2026-11-06", "资料室")
        service.calibers.bind_asset("asset-b", "cal-b", "2026-11-06", "资料室")
        reassessed = service.review.assess("impact", revision, "2026-11-06", "资料室")
        print("修正后评审：", json.dumps(reassessed, ensure_ascii=False, sort_keys=True))

        # 5. 通过交付，回执固化覆盖范围、使用条件与血缘摘要
        receipt = service.delivery.send(
            "d-1", "impact", revision, "文旅部门", "影响解释", "2026-11-07",
        )
        print("交付凭据：", json.dumps(
            {key: receipt[key] for key in
             ("id", "product_id", "product_revision", "coverage", "usage", "warnings", "lineage_digest")},
            ensure_ascii=False, sort_keys=True,
        ))
    finally:
        service.close()


if __name__ == "__main__":
    main()
