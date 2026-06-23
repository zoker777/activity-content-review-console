# 活动内容审核控制台

这是一个轻量 v1 审核控制台。项目使用 Python 标准库后端托管静态前端，属于前后端不分离架构：

```text
server.py
  ├─ 托管 static/index.html、static/app.js、static/styles.css
  ├─ 提供 /api/* 接口
  ├─ 读取原始 jsonl/images/videos
  └─ 使用 SQLite3 保存采集索引、审核状态、录入状态
```

原始笔记正文、图片、视频和原始 JSON 不写入数据库，仍然保留在原始数据目录中。

## 运行

```bash
python3 server.py
```

打开：

```text
http://127.0.0.1:8000
```

可通过环境变量或参数指定目录：

```bash
RAW_DATA_ROOT=/path/to/raw DB_PATH=/path/to/app.sqlite3 MANIFEST_PATH=/path/to/manifest.json python3 server.py
python3 server.py --raw-root /path/to/raw --db-path /path/to/app.sqlite3 --manifest-path /path/to/manifest.json --port 8000
```

常用检查：

```bash
python3 -m py_compile server.py
node --check static/app.js
```

## 原始数据目录

目录结构固定为：

```text
data/raw/
  xhs/
    球类运动/
      飞盘/
        jsonl/
          search_contents_2026-06-18.jsonl
        images/
          note_id/
            0.jpg
        videos/
          note_id/
            0.mp4
  douyin/
    球类运动/
      飞盘/
        jsonl/
          search_contents_2026-06-18.jsonl
```

约定：

- 第一层是平台，例如 `xhs`、`douyin`。
- 第二层是活动大类，例如 `球类运动`。
- 第三层是细分活动，例如 `飞盘`。
- 每个细分活动下可以有 `jsonl/`、`images/`、`videos/`。
- `jsonl/` 下每天一个文件，命名如 `search_contents_YYYY-MM-DD.jsonl`。
- `images/note_id/` 和 `videos/note_id/` 下存放该笔记的本地媒体文件。
- 图片或视频目录不存在、某篇笔记没有图片或视频，都是正常情况。

## 小红书 JSONL 字段

当前页面和后端按真实小红书 `search_contents_YYYY-MM-DD.jsonl` 结构解析，不再兼容早期样例字段。

每行一篇笔记，核心字段：

```text
note_id           笔记 ID
type              video 或 normal
title             标题
desc              正文
note_url          小红书原文链接
time              发布时间，毫秒时间戳
nickname          作者昵称
avatar            作者头像
liked_count       点赞数
collected_count   收藏数
comment_count     评论数
share_count       分享数
image_list        原始图片 URL
video_url         原始视频 URL
tag_list          逗号分隔标签
source_keyword    爬取关键词
xsec_token        小红书 token
```

后端统一返回给页面的字段包括：

```text
note_id, title, content, author, source_url, publish_time,
note_type, liked_count, collected_count, comment_count,
share_count, source_keyword, tag_list, avatar
```

其中：

- `desc` 映射为 `content`。
- `nickname` 映射为 `author`。
- `note_url` 映射为 `source_url`。
- `time` 会转换为可读时间。

## 活动清单

默认清单文件：

```text
data/manifest.json
```

清单用于声明平台、内容类别、具体方向和推荐关键词。页面左侧导航优先使用 `manifest.json`，所以还没有爬到数据的活动也会展示出来；如果原始数据目录里出现了清单之外的活动，后端也会合并显示。

接口：

```text
GET /api/manifest
GET /api/platforms
GET /api/categories?platform=xhs
GET /api/activities?platform=xhs&category=球类运动
```

## SQLite 表

SQLite3 只保存状态和索引：

- `collected_notes`：采集去重索引，唯一键为 `platform + category_name + activity_name + note_id`。
- `note_review`：审核状态，状态为 `unmarked`、`approved`、`rejected`。
- `note_submit_record`：目标系统录入状态。

数据库不保存：

- 笔记正文
- 图片
- 视频
- 原始 JSON

## 爬虫去重接口

查询是否已采集：

```text
GET /api/collected/exists?platform=xhs&category=球类运动&activity=飞盘&noteId=63003589000000001800e6be
```

下载并落盘成功后标记已采集：

```text
POST /api/collected/mark
```

请求体：

```json
{
  "platform": "xhs",
  "category": "球类运动",
  "activity": "飞盘",
  "noteId": "63003589000000001800e6be",
  "sourceFile": "xhs/球类运动/飞盘/jsonl/search_contents_2026-06-18.jsonl"
}
```

注意：爬虫应先确认原始 `jsonl/images/videos` 落盘成功，再调用 `collected/mark`。

同步当前原始数据目录到采集索引：

```text
POST /api/sync-collected
```

同步会遍历所有平台、大类和细分活动，并以活动对象的 `name` 作为目录名和 `activity_name` 写入 `collected_notes`。返回的 `synced` 是本次处理并写入/更新的笔记数量。

## 性能与缓存

为减少重复解析 JSONL 和扫描 NFS 媒体目录，后端使用 Python 进程内存缓存：

- 按 `platform + category + activity` 缓存 JSONL 解析结果和媒体文件名列表。
- JSONL 缓存依据文件路径、修改时间和大小自动失效；媒体缓存依据对应目录的修改时间自动失效。
- 最多保留最近访问的 50 个活动；30 分钟未访问的活动会自动淘汰。
- 服务重启或 K8s Pod 重建后缓存自动清空；这不会影响 SQLite 中的审核、录入和采集索引状态。

缓存只存在 Python 进程内存：不写入 SQLite、PVC 或 NFS。SQLite 仍保存业务状态，NFS/原始目录仍保存 JSONL、图片和视频。

## 页面规则

- 默认平台优先选择 `xhs`，如果没有 `xhs` 才选择平台列表第一个。
- 平台下拉选项也将 `xhs` 排在第一项，其余平台保持接口返回顺序。
- 左侧活动大类支持折叠，采用手风琴效果。
- 默认只展示 `未标记` 和 `符合` 的笔记。
- 标记 `不符合` 后，该笔记从默认可见列表隐藏。
- 标记 `符合` 后，详情页展示“录入目标系统”按钮。
- 详情页展示小红书原文入口、作者头像、发布时间、互动数据、标签、正文、图片和视频。
- 页面不展示原始 JSON。
- 详情内容全宽左对齐；只有空状态提示居中显示。
- 当前录入按钮是本地状态写入，后续可在 `/api/notes/submit` 中接入真实目标系统接口。
- 审核或录入请求成功后，页面会立即更新当前详情和左侧笔记卡片状态，不等待完整 JSONL 和媒体目录重新读取。

## 主要接口

```text
GET  /api/health
GET  /api/platforms
GET  /api/categories?platform=xhs
GET  /api/activities?platform=xhs&category=球类运动
GET  /api/notes?platform=xhs&category=球类运动&activity=飞盘&status=visible
GET  /api/note?platform=xhs&category=球类运动&activity=飞盘&noteId=...
POST /api/notes/review
POST /api/notes/submit
POST /api/sync-collected
GET  /api/media/images?platform=xhs&category=球类运动&activity=飞盘&noteId=...&file=0.jpg
GET  /api/media/videos?platform=xhs&category=球类运动&activity=飞盘&noteId=...&file=0.mp4
```

视频接口支持 HTTP Range。浏览器切换视频或取消加载时可能断开连接，后端会静默处理 `ConnectionResetError` 和 `BrokenPipeError`。

## Kubernetes 部署

K8s 清单放在：

```text
k8s/
```

部署约定：

- namespace：`devops`
- SQLite：动态 PVC，挂载到 `/app/data/db`
- SQLite 路径：`DB_PATH=/app/data/db/app.sqlite3`
- 原始数据：NFS `10.0.2.96:/data/nfs/k8s/crawl`
- 原始数据挂载：`RAW_DATA_ROOT=/app/data/raw`
- manifest：`MANIFEST_PATH=/app/data/manifest.json`
- 副本数：`replicas: 1`

SQLite 有写入操作，不要默认扩成多副本。需要多副本或多人高并发审核时，应迁移到 MySQL/PostgreSQL。

部署：

```bash
kubectl apply -k k8s/
```

临时访问：

```bash
kubectl -n devops port-forward svc/activity-review-console 8000:8000
```

验证持久化：

```bash
kubectl -n devops get pod
kubectl -n devops exec deploy/activity-review-console -- ls -l /app/data/db
kubectl -n devops exec deploy/activity-review-console -- ls -l /app/data/raw
kubectl -n devops delete pod -l app=activity-review-console
```

Pod 重建后刷新页面，审核状态仍在，说明 SQLite PVC 持久化正常。
