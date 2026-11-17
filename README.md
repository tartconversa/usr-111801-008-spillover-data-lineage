# 景区资料协作台账：景区外消费数据的口径归属

服务登记资料来源、字段、原件、使用许可、数据产品与交付凭据，并对交易汇总的来源口径、空间归属关系与合并冲突进行治理。示例主体和记录均为虚构，不连接真实文旅部门。

需要 Python 3.10 或更新版本，不依赖第三方包。

运行项目测试：python -m unittest discover -s tests -v。
检查源码：python -m compileall -q exchange。
运行本地演练：python -m exchange --database demo.db。

## 模块职责

- `catalog.py`：登记来源字段与交易汇总原件。
- `calibers.py`：版本化汇总口径（指标、时间窗、地理范围、纳入/排除规则）及原件与口径版本的绑定；修正口径另出新版本，旧版本保留。
- `spatial.py`：空间单元与归属关系登记；合作方修正以旧关系 `superseded`、新关系接续的方式留痕，层级父子与 contains/overlaps 共同判定范围重叠。
- `attribution.py`：来源归属许可，含署名要求、是否允许表述为"景区带动收入"和使用条件。
- `grants.py` 与 `policy.py`：领取方授权与辖区政策边界。
- `products.py`：编排原件为产品修订。
- `review.py`：对未发布修订做合并评审，把口径缺失、同名异义、范围重叠等阻断项与时间窗、表述限制等咨询项写入 `product_warnings`。
- `delivery.py`：交付前强制评审，阻断项未消除即拒绝；通过后固化覆盖范围、使用条件与警告快照及血缘摘要，并将修订置为已发布冻结。
- `audit.py`：登记、绑定、修正、评审、交付与拒绝均留痕，历史已交付口径可追溯。

语义与警告代码的完整说明见 `docs/domain.md`。
