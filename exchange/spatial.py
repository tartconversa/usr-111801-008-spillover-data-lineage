import hashlib
import json

from .audit import write


RELATIONS = {"contains", "overlaps", "adjacent"}


def _relation_digest(from_unit, to_unit, relation, claimant, effective_from, note):
    canonical = json.dumps(
        [from_unit, to_unit, relation, claimant, effective_from, note],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class SpatialRegistry:
    """登记空间单元与归属关系；修正以旧关系 superseded、新关系接续的方式留痕。"""

    def __init__(self, connection):
        self.connection = connection

    def register_unit(self, unit_id, name, kind, at, parent_id=None):
        if parent_id is not None and self.connection.execute(
            "SELECT 1 FROM spatial_units WHERE id=?", (parent_id,)
        ).fetchone() is None:
            raise ValueError("上级空间单元不存在")
        with self.connection:
            self.connection.execute(
                "INSERT INTO spatial_units(id,name,kind,parent_id,created_at) VALUES(?,?,?,?,?)",
                (unit_id, name, kind, parent_id, at),
            )
            write(self.connection, at, name, "spatial.unit_register", unit_id, {"kind": kind})

    def assert_relation(self, from_unit, to_unit, relation, claimant, at, note=""):
        if relation not in RELATIONS:
            raise ValueError("空间关系类型无效")
        for unit_id in (from_unit, to_unit):
            if self.connection.execute("SELECT 1 FROM spatial_units WHERE id=?", (unit_id,)).fetchone() is None:
                raise ValueError(f"空间单元不存在: {unit_id}")
        digest = _relation_digest(from_unit, to_unit, relation, claimant, at, note)
        with self.connection:
            self.connection.execute(
                "INSERT INTO spatial_relations(from_unit,to_unit,relation,claimant,effective_from,note,digest)"
                " VALUES(?,?,?,?,?,?,?)",
                (from_unit, to_unit, relation, claimant, at, note, digest),
            )
            relation_id = self.connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            write(self.connection, at, claimant, "spatial.relation_assert", str(relation_id),
                  {"from": from_unit, "to": to_unit, "relation": relation})
        return relation_id

    def correct_relation(self, old_relation_id, from_unit, to_unit, relation, claimant, at, note=""):
        """合作方修正归属：旧关系置 superseded 并封存，另立一条 active 关系。"""
        old = self.connection.execute("SELECT * FROM spatial_relations WHERE id=?", (old_relation_id,)).fetchone()
        if old is None:
            raise KeyError(old_relation_id)
        if old["status"] != "active":
            raise ValueError("被修正的空间关系已失效")
        if relation not in RELATIONS:
            raise ValueError("空间关系类型无效")
        digest = _relation_digest(from_unit, to_unit, relation, claimant, at, note)
        with self.connection:
            self.connection.execute(
                "UPDATE spatial_relations SET status='superseded', effective_to=? WHERE id=?",
                (at, old_relation_id),
            )
            self.connection.execute(
                "INSERT INTO spatial_relations(from_unit,to_unit,relation,claimant,status,supersedes_id,"
                "effective_from,note,digest) VALUES(?,?,?,?, 'active', ?,?,?,?)",
                (from_unit, to_unit, relation, claimant, old_relation_id, at, note, digest),
            )
            new_id = self.connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            write(self.connection, at, claimant, "spatial.relation_correct", str(new_id),
                  {"supersedes": old_relation_id, "from": from_unit, "to": to_unit, "relation": relation})
        return new_id

    def scopes_overlap(self, unit_a, unit_b, at=None):
        """两个空间单元在有效关系下是否存在包含或重叠（含层级父子包含）。"""
        if unit_a == unit_b:
            return True
        if self._parent_of(unit_a, unit_b) or self._parent_of(unit_b, unit_a):
            return True
        rows = self.connection.execute(
            "SELECT from_unit,to_unit,relation FROM spatial_relations WHERE status='active' "
            "AND relation IN ('contains','overlaps')"
        ).fetchall()
        undirected = set()
        for row in rows:
            undirected.add((row["from_unit"], row["to_unit"]))
            undirected.add((row["to_unit"], row["from_unit"]))
        return (unit_a, unit_b) in undirected

    def _parent_of(self, parent, child):
        """沿 parent_id 层级判断 parent 是否为 child 的上级（上级范围包含下级）。"""
        seen = set()
        current = child
        while current and current not in seen:
            row = self.connection.execute("SELECT parent_id FROM spatial_units WHERE id=?", (current,)).fetchone()
            if row is None:
                return False
            current = row["parent_id"]
            if current == parent:
                return True
            seen.add(current)
        return False

    def get_relation(self, relation_id):
        row = self.connection.execute("SELECT * FROM spatial_relations WHERE id=?", (relation_id,)).fetchone()
        if row is None:
            raise KeyError(relation_id)
        return dict(row)

    def unit(self, unit_id):
        row = self.connection.execute("SELECT * FROM spatial_units WHERE id=?", (unit_id,)).fetchone()
        if row is None:
            raise KeyError(unit_id)
        return dict(row)
