# 运行时验证 + Phase 2b White Labeling

## Context

Phase 2a 完成（FeatureModule 骨架 + Analytics 节点），但 TbSimpleAggMsgNode 未经运行时验证。
外援三轮评审一致：先运行时验证，再做 Phase 2b White Labeling（第一个真正消费 FeatureModule 的 PE 功能）。
PE 逆向已完整：White Labeling 23 个类、数据模型、API、Service 接口全部可参考。

---

## Part 1: 运行时验证 TbSimpleAggMsgNode

### 前提
- PostgreSQL localhost:5432（数据库 thingsboard，用户 postgres/postgres）
- `mvn clean package -DskipTests -pl '!msa,!ui-ngx'`

### 步骤
1. 构建 → 2. 初始化数据库（首次）→ 3. 启动 → 4. 登录 → 规则链编辑器 → 搜索 "simple aggregation" → 确认可见/可配置/可保存
5. 如果不可见：检查 plugins.scan_packages 或日志搜 ComponentDiscoveryService

**done when**: TbSimpleAggMsgNode 在规则链编辑器可见且可保存

---

## Part 2: Phase 2b White Labeling 后端最小闭环

### 目标
第一个真正走 FeatureModule 路径的 PE 功能。验证完整链路：
Flyway 建表 → DAO → Service（featureRegistry.isEnabled 门控）→ Controller → REST API

### 不做
三级 merge、域名绑定、图片缓存、子客户继承、邮件模板、前端

### 数据模型
```sql
-- V2__add_white_labeling.sql
CREATE TABLE IF NOT EXISTS white_labeling (
    tenant_id    UUID NOT NULL,
    type         VARCHAR(32) NOT NULL,
    settings     JSONB,
    created_time BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM now()) * 1000),
    PRIMARY KEY (tenant_id, type)
);
```
简化：Phase 2b 不做 customer 级别，只支持 tenant 级白标。

### 文件清单

**common/data**: WhiteLabelingParams.java, WhiteLabelingType.java
**dao**: WhiteLabelingEntity, CompositeKey, Repository, JpaWhiteLabelingDao, WhiteLabelingDao(接口), WhiteLabelingService(接口), DefaultWhiteLabelingService
**application**: WhiteLabelingController, WhiteLabelingFeatureModule
**flyway**: V2__add_white_labeling.sql
**tests**: WhiteLabelingServiceTest, (可选) WhiteLabelingControllerTest

### 门控模式
```java
// Service 层统一门控
private void checkFeatureEnabled() {
    if (!featureRegistry.isEnabled("white-labeling")) {
        throw new ThingsboardException("Feature not available", PERMISSION_DENIED);
    }
}
```

### WhiteLabelingFeatureModule
```java
@Component
public class WhiteLabelingFeatureModule implements FeatureModule {
    @Autowired FeatureRegistry featureRegistry;
    @PostConstruct void init() { featureRegistry.register(this); }
    public String getId() { return "white-labeling"; }
    public String getName() { return "White Labeling"; }
    public FeatureTier getRequiredTier() { return FeatureTier.STANDARD; }
}
```

### REST API (最小集)
- GET /api/whiteLabel/whiteLabelParams?type=GENERAL|LOGIN — 获取
- POST /api/whiteLabel/whiteLabelParams?type=GENERAL|LOGIN — 保存
- DELETE /api/whiteLabel/whiteLabelParams?type=GENERAL|LOGIN — 删除
- GET /api/whiteLabel/isWhiteLabelingAllowed — 检查是否启用

### 执行顺序
1. Flyway 迁移 → 2. DTO + 枚举 (common/data) → 3. Entity + DAO (dao) → 4. Service + 门控 (dao) → 5. FeatureModule + Controller (application) → 6. 测试 → 7. ECS verify

### PE 参考文件
- pe-analysis/decompiled/application/.../controller/WhiteLabelingController.java
- pe-analysis/decompiled/dao-4.3.1PE/.../model/sql/WhiteLabelingEntity.java
- pe-analysis/decompiled/dao-4.3.1PE/.../wl/BaseWhiteLabelingService.java
- pe-analysis/decompiled/data-4.3.1PE/.../wl/WhiteLabelingParams.java

### 纪律
- 不改 BaseController (phase2-discipline.md)
- 门控在 Service 层 (FeatureRegistry.isEnabled)
- 复用 PERMISSION_DENIED，不加新 ErrorCode
