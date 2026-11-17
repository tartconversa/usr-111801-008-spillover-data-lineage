from .audit import write


class AttributionLicenses:
    """来源的归属许可：对外引用时的署名要求、表述边界与使用条件。

    同一来源颁发新许可时，旧许可置 superseded 保留，历史交付仍按当时快照追溯。
    """

    def __init__(self, connection):
        self.connection = connection

    def issue(self, license_id, source_id, citation_term, scenic_claim_allowed,
              usage_condition, valid_until, at, actor):
        if self.connection.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone() is None:
            raise KeyError(source_id)
        with self.connection:
            self.connection.execute(
                "UPDATE attribution_licenses SET status='superseded' WHERE source_id=? AND status='active'",
                (source_id,),
            )
            self.connection.execute(
                "INSERT INTO attribution_licenses(id,source_id,citation_term,scenic_claim_allowed,"
                "usage_condition,valid_until,status,issued_at) VALUES(?,?,?,?,?,?, 'active',?)",
                (license_id, source_id, citation_term, int(scenic_claim_allowed),
                 usage_condition, valid_until, at),
            )
            write(self.connection, at, actor, "attribution.issue", license_id,
                  {"source": source_id, "scenic_claim_allowed": bool(scenic_claim_allowed)})

    def active_for(self, source_id, at):
        """返回 at 时点有效的归属许可；无有效许可时返回 None（交付按阻断处理）。"""
        return self.connection.execute(
            "SELECT * FROM attribution_licenses WHERE source_id=? AND status='active' AND valid_until>=?",
            (source_id, at),
        ).fetchone()
