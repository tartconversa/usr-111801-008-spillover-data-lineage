import sqlite3


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, jurisdiction TEXT NOT NULL,
    classification TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS fields (
    source_id TEXT NOT NULL REFERENCES sources(id), name TEXT NOT NULL,
    meaning TEXT NOT NULL, kind TEXT NOT NULL, sensitive INTEGER NOT NULL,
    PRIMARY KEY(source_id,name)
);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    schema_version INTEGER NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL,
    received_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    recipient TEXT NOT NULL, purpose TEXT NOT NULL, valid_until TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS policies (
    jurisdiction TEXT NOT NULL, classification TEXT NOT NULL, purpose TEXT NOT NULL,
    decision TEXT NOT NULL, revision INTEGER NOT NULL,
    PRIMARY KEY(jurisdiction,classification,purpose)
);
CREATE TABLE IF NOT EXISTS products (
    id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL,
    PRIMARY KEY(id,revision)
);
CREATE TABLE IF NOT EXISTS product_inputs (
    product_id TEXT NOT NULL, product_revision INTEGER NOT NULL,
    asset_id TEXT NOT NULL REFERENCES assets(id),
    PRIMARY KEY(product_id,product_revision,asset_id),
    FOREIGN KEY(product_id,product_revision) REFERENCES products(id,revision)
);
-- 空间单元：景区、街区、商圈、城区、城市等，parent_id 表示行政或管理层级
CREATE TABLE IF NOT EXISTS spatial_units (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
    parent_id TEXT REFERENCES spatial_units(id), created_at TEXT NOT NULL
);
-- 空间归属关系：合作方提出，修正时旧关系置 superseded、新关系接续
CREATE TABLE IF NOT EXISTS spatial_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_unit TEXT NOT NULL REFERENCES spatial_units(id),
    to_unit TEXT NOT NULL REFERENCES spatial_units(id),
    relation TEXT NOT NULL, claimant TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    supersedes_id INTEGER REFERENCES spatial_relations(id),
    effective_from TEXT NOT NULL, effective_to TEXT,
    note TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL
);
-- 汇总口径：版本化定义，修正口径时旧版本置 superseded，已绑定原件不动
CREATE TABLE IF NOT EXISTS calibers (
    id TEXT NOT NULL, revision INTEGER NOT NULL,
    metric TEXT NOT NULL, metric_category TEXT NOT NULL, method TEXT NOT NULL,
    window_start TEXT NOT NULL, window_end TEXT NOT NULL, granularity TEXT NOT NULL,
    scope_units TEXT NOT NULL, include_rule TEXT NOT NULL, exclude_rule TEXT NOT NULL,
    owner TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
    supersedes_revision INTEGER, digest TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(id,revision)
);
-- 原件与口径版本的绑定：一份交易汇总对应一个口径版本
CREATE TABLE IF NOT EXISTS asset_calibers (
    asset_id TEXT PRIMARY KEY REFERENCES assets(id),
    caliber_id TEXT NOT NULL, caliber_revision INTEGER NOT NULL,
    bound_at TEXT NOT NULL,
    FOREIGN KEY(caliber_id,caliber_revision) REFERENCES calibers(id,revision)
);
-- 来源归属许可：对外引用时的署名与表述条件
CREATE TABLE IF NOT EXISTS attribution_licenses (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    citation_term TEXT NOT NULL, scenic_claim_allowed INTEGER NOT NULL,
    usage_condition TEXT NOT NULL, valid_until TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active', issued_at TEXT NOT NULL
);
-- 产品修订上的合并评审警告：blocking=1 为不可合并之处
CREATE TABLE IF NOT EXISTS product_warnings (
    product_id TEXT NOT NULL, product_revision INTEGER NOT NULL,
    code TEXT NOT NULL, blocking INTEGER NOT NULL,
    subject TEXT NOT NULL, detail TEXT NOT NULL,
    FOREIGN KEY(product_id,product_revision) REFERENCES products(id,revision)
);
CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY, product_id TEXT NOT NULL, product_revision INTEGER NOT NULL,
    recipient TEXT NOT NULL, purpose TEXT NOT NULL, created_at TEXT NOT NULL,
    input_digest TEXT NOT NULL, policy_revisions TEXT NOT NULL,
    coverage_snapshot TEXT, usage_snapshot TEXT, warning_snapshot TEXT,
    lineage_digest TEXT,
    FOREIGN KEY(product_id,product_revision) REFERENCES products(id,revision)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
    action TEXT NOT NULL, subject TEXT NOT NULL, details TEXT NOT NULL
);
"""

# 早期台账的 deliveries 表缺少快照列，按列名补齐，保留历史交付行
_DELIVERY_ADDED_COLUMNS = ("coverage_snapshot", "usage_snapshot", "warning_snapshot", "lineage_digest")


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    existing = {row[1] for row in connection.execute("PRAGMA table_info(deliveries)")}
    for column in _DELIVERY_ADDED_COLUMNS:
        if column not in existing:
            connection.execute(f"ALTER TABLE deliveries ADD COLUMN {column} TEXT")
    connection.commit()
    return connection
