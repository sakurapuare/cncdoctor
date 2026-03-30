# Shukongdashi

数控机床故障诊断系统，已完成一次破坏性重构。

## 这次重构解决了什么

原项目的主要问题：

- 运行时硬编码了 `SECRET_KEY`、Neo4j 账号密码、MySQL `root/root`
- 视图直接写业务逻辑，诊断、问答、补全、在线分析、反馈全部耦合在脚本函数里
- 导入模块即连接数据库、加载模型，启动链路不可控
- 依赖锁死在 `Django 2.2 + TensorFlow 1.14 + py2neo 4`，在现代 Python 环境下基本不可运行
- 反馈数据只写外部 MySQL，仓库本身无法自包含
- 在线分析通过中间文件落盘，且异常处理和超时控制很弱

已完成的改造：

- 删除仓库中的硬编码账号口令和导出元数据
- 新增面向对象核心层：领域模型、文本解析、仓储、服务容器、接口视图
- 将案例库内置到本地 SQLite 仓储，首次运行自动从 `guzhanganli.sql` 导入
- Neo4j 和 CNN 改为可选依赖，不再阻断系统启动
- 诊断、问答、补全、在线分析、反馈全部改为统一服务对象
- Django 路由改为 class-based views，接口返回统一 JSON 结构
- API 同时支持 `GET`、表单 `POST`、JSON `POST`，并兼容带或不带 `/` 的路径
- API 统一附带跨域响应头，并支持 `OPTIONS` 预检
- 新增 `/docs` 自描述接口、`rebuild_case_db`/`system_doctor` 运维命令
- 重复反馈保存会自动去重，不会再因为唯一约束导致报错
- 删除无引用的旧试验脚本和中间产物，收敛仓库结构
- 旧 `demo/question_*.py` 模块保留为兼容壳，不再承载业务逻辑

## 新架构

核心目录：

```text
Shukongdashi/
├── api_views.py              # Django API 入口
├── core/
│   ├── container.py          # 服务容器
│   ├── models.py             # 领域对象
│   ├── repositories.py       # SQLite/Neo4j 仓储
│   ├── services.py           # 诊断/问答/补全/反馈/在线分析
│   └── text.py               # 文本解析、分类、相似度
├── runtime/
│   └── fault_cases.sqlite3   # 运行时案例库，首次启动自动生成
└── settings.py               # 环境变量驱动的 Django 配置
```

## 功能说明

### 1. 故障诊断 `/qa`

- 输入品牌、型号、报警码、故障描述、关联现象
- 优先使用图谱推理
- 图谱不可用时自动降级到本地案例相似度诊断

### 2. 在线分析 `/pa`

- 尝试使用在线搜索抓取相似结果
- 网络不可用时自动回退到本地案例库推荐

### 3. 反馈保存 `/save`

- 将用户反馈直接写入本地案例库
- 如果配置了 Neo4j，则同步补充知识图谱关系

### 4. 自动补全 `/buquan`

- 同时从本地案例库和图谱描述中生成候选补全

### 5. 智能问答 `/wenda`

- 支持故障原因、操作、故障部位、报警含义四类问答
- 图谱不可用时回退到案例库检索

### 6. 接口文档 `/docs`

- 返回所有主要接口的路径、方法、参数和统一响应结构

## 接口返回格式

所有接口统一返回：

```json
{
  "code": 0,
  "msg": "成功",
  "data": {}
}
```

## 环境变量

参考 `.env.example`：

```bash
export DJANGO_SECRET_KEY="replace-this"
export DJANGO_DEBUG=1
export DJANGO_LOG_LEVEL="INFO"
export DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost"

export APP_ENABLE_ONLINE_SEARCH=1
export APP_WEB_SEARCH_TIMEOUT=8
export APP_CASE_DB_PATH="./Shukongdashi/runtime/fault_cases.sqlite3"
export APP_CASE_SQL_SEED="./guzhanganli.sql"
export APP_DEMO_DIR="./Shukongdashi/demo"

export APP_CORS_ALLOW_ORIGIN="*"
export APP_CORS_ALLOW_METHODS="GET,POST,OPTIONS"
export APP_CORS_ALLOW_HEADERS="Content-Type,Authorization,X-Requested-With"

export APP_NEO4J_URI="http://127.0.0.1:7474"
export APP_NEO4J_USER="neo4j"
export APP_NEO4J_PASSWORD="replace-this"
```

不配置 Neo4j 时，系统仍可运行，只是图谱推理能力会自动关闭。

## 安装与启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirement.txt
python manage.py runserver 0.0.0.0:8000
```

也可以直接使用：

```bash
make setup
make test
make check
make run
```

## 运维命令

```bash
python manage.py rebuild_case_db
python manage.py system_doctor
```

## 建议的验证顺序

```bash
python -m unittest discover -s tests
python manage.py check
```

## 破坏性变更说明

- API 返回结构从“裸字典/字符串”统一为 `code/msg/data`
- MySQL 依赖已被移除，反馈写入本地 SQLite
- TensorFlow CNN 不再是强依赖，未安装时使用启发式分类器
- Neo4j 不再写死在代码中，需要通过环境变量显式配置
- 仓库中的旧试验脚本、废弃实现和运行中间文件已移除
