# 活动内容审核控制台

这是一个轻量 v1 实现：原始笔记正文、图片、视频都保留在数据源目录中，SQLite3 只保存采集去重索引、审核状态和录入状态。

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
RAW_DATA_ROOT=/path/to/raw DB_PATH=/path/to/app.sqlite3 python3 server.py
python3 server.py --raw-root /path/to/raw --db-path /path/to/app.sqlite3 --manifest-path /path/to/manifest.json --port 8000
```

## 原始数据目录

```text
data/raw/
  xhs/
    球类运动/
      飞盘/
        jsonl/
          search_contents_2026-06-17.jsonl
        images/
          note_id/
            1.jpg
        videos/
          note_id/
            1.mp4
  douyin/
    球类运动/
      飞盘/
        jsonl/
          search_contents_2026-06-17.jsonl
```

图片或视频目录不存在、某篇笔记没有图片或视频，都属于正常情况。

## 活动清单

默认清单文件：

```text
data/manifest.json
```

清单用于声明平台、内容类别、具体方向和推荐关键词。页面左侧导航优先使用 `manifest.json`，所以还没有爬到数据的活动也会展示出来；如果原始数据目录里出现了清单之外的活动，后端也会合并显示。

示例结构：

```json
{
  "platforms": ["xhs", "douyin"],
  "categories": [
    {
      "name": "球类运动",
      "activities": [
        {
          "name": "飞盘",
          "keywords": ["飞盘搭子", "飞盘组局", "周末飞盘"]
        }
      ]
    }
  ]
}
```

接口：

```text
GET /api/manifest
GET /api/categories?platform=xhs
GET /api/activities?platform=xhs&category=球类运动
```

## SQLite 表

- `collected_notes`：采集去重索引，唯一键为 `platform + category_name + activity_name + note_id`。
- `note_review`：审核状态，状态为 `unmarked`、`approved`、`rejected`。
- `note_submit_record`：目标系统录入状态。

数据库不保存笔记正文、原始 JSON、图片或视频文件。

## 爬虫去重接口

查询是否已采集：

```text
GET /api/collected/exists?platform=xhs&category=球类运动&activity=飞盘&noteId=xhs-frisbee-001
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
  "noteId": "xhs-frisbee-001",
  "sourceFile": "xhs/球类运动/飞盘/jsonl/search_contents_2026-06-17.jsonl"
}
```

也可以在页面点击“同步采集索引”，把当前原始目录里的 jsonl 扫描进 `collected_notes`。

## 页面规则

- 默认只展示未标记和符合。
- 标记不符合后，笔记会从“可见”列表隐藏。
- 标记符合后，详情页展示录入按钮。
- 当前录入按钮是本地状态写入，后续可在 `/api/notes/submit` 中接入真实目标系统接口。
