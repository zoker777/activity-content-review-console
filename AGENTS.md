# AGENTS.md

## 回复语言

始终使用简体中文回复用户。

## 项目概览

这是“活动内容审核控制台”，当前是轻量 v1：

- `server.py` 使用 Python 标准库实现 HTTP 服务、API、SQLite 访问和媒体文件读取。
- `static/index.html`、`static/app.js`、`static/styles.css` 是原生 HTML/CSS/JS 前端。
- 前后端不分离，由 `server.py` 同时托管静态页面和 `/api/*` 接口。
- `data/manifest.json` 是平台、活动大类、细分活动和推荐关键词清单。
- `k8s/` 存放 Kubernetes 部署资源。

## 运行与检查

本地运行：

```bash
python3 server.py
```

常用检查：

```bash
python3 -m py_compile server.py
node --check static/app.js
```

常用环境变量：

```text
RAW_DATA_ROOT=/path/to/raw
DB_PATH=/path/to/app.sqlite3
MANIFEST_PATH=/path/to/manifest.json
HOST=0.0.0.0
PORT=8000
```

## 数据目录约定

原始数据目录结构：

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
```

不要把笔记正文、图片、视频或原始 JSON 写入 SQLite。页面内容应直接从 `jsonl/images/videos` 读取。

## 小红书字段映射

当前只适配真实小红书 JSONL 字段，不再兼容早期样例字段。

关键映射：

```text
note_id      -> note_id
title        -> title
desc         -> content
nickname     -> author
note_url     -> source_url
time         -> publish_time
type         -> note_type
avatar       -> avatar
tag_list     -> tag_list
source_keyword -> source_keyword
```

互动字段：

```text
liked_count
collected_count
comment_count
share_count
```

修改解析逻辑时，不要重新引入 `source_url/url/share_url/content/author` 等旧字段兼容，除非用户明确要求。

## SQLite 边界

SQLite 只保存三类数据：

- `collected_notes`：采集去重索引。
- `note_review`：审核状态。
- `note_submit_record`：目标系统录入状态。

唯一键约定：

```text
platform + category_name + activity_name + note_id
```

爬虫应在原始数据成功落盘后，再调用采集标记接口写入 `collected_notes`。

## 页面规则

- 默认平台优先选择 `xhs`。
- 左侧活动大类支持折叠，采用手风琴效果。
- 默认列表只展示 `unmarked` 和 `approved`。
- `rejected` 从默认可见列表隐藏。
- 详情页展示小红书原文入口、作者头像、发布时间、互动数据、标签、正文、图片和视频。
- 页面不展示原始 JSON。
- 标记 `approved` 后才展示录入目标系统按钮。

## K8s 约定

Kubernetes 清单在 `k8s/`。

固定约定：

```text
namespace: devops
SQLite PVC mount: /app/data/db
DB_PATH: /app/data/db/app.sqlite3
NFS raw data: 10.0.2.96:/data/nfs/k8s/crawl
RAW_DATA_ROOT: /app/data/raw
MANIFEST_PATH: /app/data/manifest.json
replicas: 1
```

SQLite 有写入操作，不要默认改成多副本。如果需要多副本，应先迁移到 MySQL/PostgreSQL。

## 修改约束

- 优先保持原生 HTML/CSS/JS，不要为小交互引入 Vue/React。
- 不要把原始 JSON 重新展示到页面，除非用户明确要求。
- 不要把图片或视频文件路径直接暴露为服务器绝对路径，应继续通过 `/api/media/*` 读取。
- 媒体接口需要保留路径校验和 HTTP Range 支持。
- 浏览器取消视频请求导致的 `ConnectionResetError`、`BrokenPipeError` 属于正常行为，应静默处理。
