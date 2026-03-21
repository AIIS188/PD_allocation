# PD FastAPI Starter

[![wakatime](https://wakatime.com/badge/user/d46234d8-e044-4d0d-b6d9-2789ecdaca27/project/c10939fa-88e9-4557-b299-db1defe6618b.svg)](https://wakatime.com/badge/user/d46234d8-e044-4d0d-b6d9-2789ecdaca27/project/c10939fa-88e9-4557-b299-db1defe6618b)

## 快速开始

### 1) 安装 uv 并创建虚拟环境

```bash
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境
uv venv
```

### 2) 安装依赖

```bash
uv sync
# 如使用 EmailStr 字段，请确保安装 email-validator
uv add email-validator
```

合同 OCR、磅单等能力依赖 `rapidocr-onnxruntime`、`opencv-contrib-python` 等（见 `pyproject.toml`）。若未安装相关包，与合同 OCR 相关的模块可能无法在导入阶段加载。

### 3) 配置环境变量

推荐使用 `.env`。**应用运行时通过 PyMySQL 连接数据库，实际读取的是下列 `MYSQL_*` 变量**（与 `database_setup.py` 一致）。`app/core/config.py` 中的 `DATABASE_URL` 目前主要用于配置项占位，**请勿只配 `DATABASE_URL` 而省略 `MYSQL_*`**。

```
APP_NAME=PD API
JWT_SECRET=请改为足够长的随机串
JWT_ALGORITHM=HS256

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=123456
MYSQL_DATABASE=PD_db
MYSQL_CHARSET=utf8mb4

# 监听端口（main.py 使用，默认 8007）
PORT=8007

# 可选：逗号分隔，默认 *
# CORS_ALLOW_ORIGINS=http://127.0.0.1:3000,http://localhost:3000

# 可选：日志目录与级别
# LOG_DIR=logs
# LOG_LEVEL=INFO
```

### 4) 初始化/同步数据库表结构

```bash
# 一次性创建基础表（或补齐缺失索引/列）
python database_setup.py
```

### 5) 运行应用

```bash
# 快速运行（开发环境，含热重载）
uv run main.py

# 或直接使用 uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8007
```

### 6) 访问地址

默认端口以环境变量 `PORT` 为准（未设置时为 `8007`）：

- Swagger 文档: http://127.0.0.1:8007/docs

## 应用行为摘要

- **启动时**：会执行 `create_tables()` 做表结构检查/创建，并启动定时任务（默认每天 00:10，上海时区）将到期合同批量标记为「已失效」（宽限逻辑见 `expire_contracts_after_grace`）。
- **鉴权**：见下文「接口鉴权说明」。

## API 详细说明

### 通用

- `GET /healthz`：健康检查。
- `GET /init-db`：手动触发数据库初始化（**仅建议开发/调试使用，生产环境应关闭或加保护**）。

### 用户与权限（PD 用户体系，前缀 `/api/v1/user`）

登录成功后，需要携带请求头：`Authorization: Bearer <token>`。

- `POST /api/v1/user/auth/login`：登录，校验账号密码并返回 JWT。
- `POST /api/v1/user/auth/logout`：登出（需有效 Token；前端仍应清除本地 Token）。
- `POST /api/v1/user/auth/refresh`：刷新访问令牌（需有效 Token）。
- `GET /api/v1/user/me`：当前用户信息。
- `PUT /api/v1/user/me`：更新当前用户资料（不含角色）。
- `PUT /api/v1/user/me/password`：修改当前用户密码。
- `POST /api/v1/user/users`：创建用户（管理员/大区经理）。
- `GET /api/v1/user/users`：用户列表（分页/筛选，管理员/大区经理）。
- `GET /api/v1/user/users/{user_id}`：用户详情。
- `PUT /api/v1/user/users/{user_id}`：更新用户。
- `DELETE /api/v1/user/users/{user_id}`：软删除用户。
- `POST /api/v1/user/users/{user_id}/reset-password`：管理员重置密码（具体约束见接口实现）。

权限相关子路由（若已启用）见 `/docs` 中 **用户认证与权限** 分组。

### 合同管理（`/api/v1/contracts`）

- `POST /api/v1/contracts/ocr`：上传合同图片，OCR 识别；可选自动保存与图片落盘。**自动写入数据库时**须带查询参数 `plan_no`（报货计划编号，即 `pd_delivery_plans.plan_no`）。
- `POST /api/v1/contracts/manual`：手动录入合同（含品种与单价明细）；请求 JSON **必须**包含 `plan_no`（同上）；服务端会解析为 `delivery_plan_id` 落库。
- `GET /api/v1/contracts`：分页列表，支持精确条件与模糊关键词。
- `GET /api/v1/contracts/{contract_id}`：详情（含品种明细）。
- `GET /api/v1/contracts/{contract_id}/image`：预览合同图片。
- `PUT /api/v1/contracts/{contract_id}`：更新合同与品种明细。
- `DELETE /api/v1/contracts/{contract_id}`：删除合同。
- `POST /api/v1/contracts/export`：导出 CSV（合同 ID 列表为空可表示导出全部，以实际接口行为为准）。

### 客户管理（`/api/v1/customers`）

- `POST /api/v1/customers`：创建客户。
- `GET /api/v1/customers`：列表。
- `GET /api/v1/customers/{customer_id}`：详情。
- `PUT /api/v1/customers/{customer_id}`：更新。
- `DELETE /api/v1/customers/{customer_id}`：删除。

### 销售台账/报货订单（`/api/v1/deliveries`）

- `POST /api/v1/deliveries`：新增报货订单/销售台账。
- `GET /api/v1/deliveries`：列表。
- `GET /api/v1/deliveries/{delivery_id}`：单条详情。
- `GET /api/v1/deliveries/{delivery_id}/image`：预览联单图片。
- `PUT /api/v1/deliveries/{delivery_id}`：更新。
- `DELETE /api/v1/deliveries/{delivery_id}`：删除。
- `POST /api/v1/deliveries/{delivery_id}/upload-order`：上传报货单附件。
- **报单合同品类单价**（表 `pd_delivery_contract_product_prices`，按报单 `delivery_id` 存关联合同的品类与单价，可与合同品种表独立改价）：
  - `GET /api/v1/deliveries/{delivery_id}/contract-product-prices`：列表。
  - `POST /api/v1/deliveries/{delivery_id}/contract-product-prices/sync-from-contract`：按报单当前关联合同，从 `pd_contract_products` **全量覆盖**写入本表（需登录）。
  - `PATCH /api/v1/deliveries/{delivery_id}/contract-product-prices`：批量改单价（需登录）； body：`{"items":[{"id":1,"unit_price":8500}]}` 或 `{"items":[{"product_name":"电动车","unit_price":8500}]}`。

### 订货计划（`/api/v1/order-plans`）

- `POST /api/v1/order-plans/`：录入（需登录）； body：`plan_no`（报货计划编号）、`truck_count`；自动带入报货计划的冶炼厂；审核状态默认「待审核」。
- `GET /api/v1/order-plans/`：分页列表；支持 `audit_status`、`plan_no`、`smelter_name`、`operator_name`、`updated_from`、`updated_to` 等查询参数。
- `GET /api/v1/order-plans/{id}`：详情。
- `PATCH /api/v1/order-plans/{id}/truck-count`：仅改车数（需登录）；非「会计」角色修改后状态重置为「待审核」，「会计」不改状态。
- `POST /api/v1/order-plans/{id}/audit`：审核（需登录）； body：`audit_result` 为「审核通过」或「审核未通过」，可选 `remark`。仅「待审核」可审；**通过**时按本条 `truck_count` 调用与 `POST /delivery-plans/increment-confirmed-trucks` 相同的累加规则更新报货计划的 `confirmed_trucks` / `unconfirmed_trucks`（`truck_count` 为 0 时不改报货计划；已定车数可超过计划车数，此时未定车数为 0）。

### 磅单管理（`/api/v1/weighbills`）

- `POST /api/v1/weighbills/ocr`：上传磅单图片并 OCR。
- `POST /api/v1/weighbills/create`：新增磅单（按品种上传）。
- `GET /api/v1/weighbills`：列表。
- `GET /api/v1/weighbills/{bill_id}`：详情。
- `GET /api/v1/weighbills/{bill_id}/image`：预览图片。
- `PUT /api/v1/weighbills/modify`：更新磅单（含图片）。
- `DELETE /api/v1/weighbills/{bill_id}`：删除。
- `POST /api/v1/weighbills/{bill_id}/confirm`：确认/锁定。
- `GET /api/v1/weighbills/match/delivery`：匹配磅单与报货订单。
- `GET /api/v1/weighbills/contract/price`：按合同查价格信息。

### 磅单结余 / 支付回单（`/api/v1/balances` 等）

- 磅单上传/修改成功后可自动生成结余明细；也可手动 `POST /api/v1/balances/generate`（以实际路由为准）。
- 支付回单、结余核销等完整列表见 http://127.0.0.1:8007/docs 中 **磅单结余管理**、**收款明细管理** 等分组。

### 品类管理（`/api/v1/product-categories`）

- `GET /api/v1/product-categories/`：查询固定 50 槽位品类列表。
- `POST /api/v1/product-categories/`：新增品类（写入第一个空槽位）。
- `DELETE /api/v1/product-categories/`：按名称删除品类（槽位置空）。

## 接口鉴权说明（当前实现）

- **已挂载**：`main.py` 中通过 `register_pd_auth_routes` 注册了 `/api/v1/user` 下的登录与用户管理路由；业务 API 挂载在 `/api/v1` 下。
- **全局 `HTTPBearer(auto_error=False)`** 不会自动拒绝未带 Token 的请求；**是否必须登录取决于各路由是否声明 `Depends(get_current_user)`**。
- **当前大致情况**（以代码为准，迭代后请以 `/docs` 为准）：
  - **报货 `deliveries`、收款 `payment`、磅单 `weighbills` 中部分接口**已使用 JWT 校验当前用户。
  - **合同 `contracts`、客户 `customers`、结余 `balances`、品类 `product_categories` 等多数接口**当前未统一强制 Token，**存在匿名可调用的风险**。
- 生产环境建议：在网关层统一鉴权，或逐步为上述路由补上 `get_current_user` 与角色/权限校验。

## 安全性说明

- **务必修改 `JWT_SECRET`**，勿使用示例默认值。
- **`GET /init-db` 无鉴权**，勿对公网开放。
- **业务接口鉴权未全覆盖**，见上一节。
- 用户体系中若存在「重置密码 / 管理密钥」类参数，部署时需通过环境变量或密钥管理妥善配置，勿提交到仓库。

## 开发与架构备注

- 数据库连接：`core/database.py` 的 `get_conn()` 使用 `DictCursor`；部分历史代码从 `contract_service` 引入另一套 `get_conn()`（默认游标），行为略有差异，后续可考虑统一到单一入口。
- 请求日志中间件会为日志注入当前用户上下文；若需审计对齐用户维度，可关注相关实现是否在记录前重置了上下文（见 `main.py` 中 `request_logger`）。
