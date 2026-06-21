# Kubernetes 部署清单

当前清单使用：

- SQLite 动态 PVC：`activity-review-sqlite-pvc`
- 原始数据 NFS：`10.0.2.96:/data/nfs/k8s/crawl`
- 应用单副本：SQLite 写入场景下不要扩多副本
- 服务端口：`8000`

## 部署

先把 `k8s/deployment.yaml` 里的镜像替换为实际镜像：

```yaml
image: activity-review-console:latest
```

然后执行：

```bash
kubectl apply -k k8s/
```

## 访问

集群内服务：

```text
activity-review-console.devops.svc.cluster.local:8000
```

本地临时访问：

```bash
kubectl -n devops port-forward svc/activity-review-console 8000:8000
```

打开：

```text
http://127.0.0.1:8000
```

## 验证持久化

```bash
kubectl -n devops get pod
kubectl -n devops exec deploy/activity-review-console -- ls -l /app/data/db
kubectl -n devops exec deploy/activity-review-console -- ls -l /app/data/raw
```

在页面标记一篇笔记后，删除 Pod：

```bash
kubectl -n devops delete pod -l app=activity-review-console
```

Pod 重建后刷新页面，审核状态仍在，说明 SQLite PVC 持久化正常。

## 注意

- `RAW_DATA_ROOT=/app/data/raw` 对应 NFS 挂载目录。
- `DB_PATH=/app/data/db/app.sqlite3` 对应 SQLite PVC。
- `MANIFEST_PATH=/app/data/manifest.json` 默认要求镜像内包含 `data/manifest.json`。
- 如果 NFS 目录内不是直接以 `xhs/`、`douyin/` 开头，需要调整 NFS path 或 `RAW_DATA_ROOT`。
