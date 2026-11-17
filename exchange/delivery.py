import hashlib
import json

from .audit import write
from .attribution import AttributionLicenses
from .calibers import Calibers
from .grants import Grants
from .policy import Policies
from .products import Products
from .review import MergeReview


def _canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Delivery:
    def __init__(self, connection):
        self.connection = connection
        self.grants = Grants(connection)
        self.policies = Policies(connection)
        self.products = Products(connection)
        self.calibers = Calibers(connection)
        self.licenses = AttributionLicenses(connection)
        self.review = MergeReview(connection)

    def send(self, delivery_id, product_id, revision, recipient, purpose, at, actor=None):
        existing = self.connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if existing:
            if (existing["product_id"], existing["product_revision"], existing["recipient"], existing["purpose"]) != (product_id, revision, recipient, purpose):
                raise ValueError("交付编号已用于其他请求")
            return self._credential(dict(existing))
        product = self.connection.execute("SELECT state FROM products WHERE id=? AND revision=?", (product_id, revision)).fetchone()
        if product is None or product["state"] != "draft":
            raise ValueError("数据产品修订不可交付")
        # 交付前重新评审：合作方修正口径或空间归属后，未发布修订的不可合并之处须重新标出
        warnings = self.review.assess(product_id, revision, at, actor or recipient)
        blocking = [item for item in warnings if item["blocking"]]
        inputs = self.products.inputs(product_id, revision)
        if not inputs:
            raise ValueError("数据产品缺少输入")
        reasons = [{"source": item["subject"], "reason": item["code"]} for item in blocking]
        policy_revisions = {}
        for asset in inputs:
            source_id = asset["source_id"]
            if asset["state"] != "active" or not asset["source_active"]:
                reasons.append({"source": source_id, "reason": "inactive"})
            if not self.grants.permits(source_id, recipient, purpose, at):
                reasons.append({"source": source_id, "reason": "grant"})
            decision, policy_revision = self.policies.decision(asset["jurisdiction"], asset["classification"], purpose)
            policy_revisions[source_id] = policy_revision
            if decision != "allow":
                reasons.append({"source": source_id, "reason": "policy"})
        if reasons:
            with self.connection:
                write(self.connection, at, recipient, "delivery.reject", product_id,
                      {"revision": revision, "reasons": reasons})
            raise PermissionError(reasons)

        coverage = self._coverage_snapshot(inputs)
        usage = self._usage_snapshot(inputs, recipient, purpose, at, policy_revisions)
        warning_snapshot = warnings
        digest = hashlib.sha256(
            "|".join(asset["digest"] for asset in inputs).encode()
        ).hexdigest()
        lineage_digest = hashlib.sha256(_canonical({
            "input_digest": digest,
            "policy_revisions": policy_revisions,
            "coverage": coverage,
            "usage": usage,
            "warnings": warning_snapshot,
        }).encode()).hexdigest()
        with self.connection:
            self.connection.execute(
                "INSERT INTO deliveries(id,product_id,product_revision,recipient,purpose,created_at,"
                "input_digest,policy_revisions,coverage_snapshot,usage_snapshot,warning_snapshot,lineage_digest)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (delivery_id, product_id, revision, recipient, purpose, at, digest,
                 json.dumps(policy_revisions, sort_keys=True),
                 json.dumps(coverage, ensure_ascii=False, sort_keys=True),
                 json.dumps(usage, ensure_ascii=False, sort_keys=True),
                 json.dumps(warning_snapshot, ensure_ascii=False, sort_keys=True),
                 lineage_digest),
            )
            # 交付即发布冻结：此后口径或空间关系修正不再改变本回执
            self.connection.execute(
                "UPDATE products SET state='published' WHERE id=? AND revision=?",
                (product_id, revision),
            )
            write(self.connection, at, recipient, "delivery.accept", product_id,
                  {"delivery_id": delivery_id, "revision": revision,
                   "inputs": [a["id"] for a in inputs], "lineage_digest": lineage_digest})
        row = dict(self.connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone())
        return self._credential(row)

    def _coverage_snapshot(self, inputs):
        """覆盖范围快照：每份原件绑定的口径全文与空间单元，交付后不随后续修正变化。"""
        snapshot = []
        for asset in inputs:
            caliber = self.calibers.asset_caliber(asset["id"])
            snapshot.append({
                "asset_id": asset["id"],
                "source_id": asset["source_id"],
                "owner": asset["owner"],
                "jurisdiction": asset["jurisdiction"],
                "caliber": caliber,
            })
        return snapshot

    def _usage_snapshot(self, inputs, recipient, purpose, at, policy_revisions):
        """使用条件快照：按来源记录归属许可、许可授权与政策决策。"""
        sources = {}
        for asset in inputs:
            source_id = asset["source_id"]
            if source_id in sources:
                continue
            license_row = self.licenses.active_for(source_id, at)
            sources[source_id] = {
                "source_id": source_id,
                "attribution": None if license_row is None else {
                    "citation_term": license_row["citation_term"],
                    "scenic_claim_allowed": bool(license_row["scenic_claim_allowed"]),
                    "usage_condition": license_row["usage_condition"],
                    "valid_until": license_row["valid_until"],
                },
                "grant_id": self.grants.permits(source_id, recipient, purpose, at),
                "policy_revision": policy_revisions.get(source_id, 0),
            }
        return {
            "recipient": recipient,
            "purpose": purpose,
            "at": at,
            "sources": [sources[key] for key in sorted(sources)],
        }

    def _credential(self, row):
        parsed_columns = {
            "coverage_snapshot": "coverage",
            "usage_snapshot": "usage",
            "warning_snapshot": "warnings",
        }
        for column, target in parsed_columns.items():
            if row.get(column):
                row[target] = json.loads(row[column])
        return row
