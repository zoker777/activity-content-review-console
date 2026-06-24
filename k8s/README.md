# Kubernetes 部署清单

当前清单使用：

- SQLite NFS：`10.0.2.96:/data/nfs/k8s/crawl/db`
- 原始数据 NFS：`10.0.2.96:/data/nfs/k8s/crawl/raw`
- 应用单副本：SQLite 写入场景下不要扩多副本
- 服务端口：`8000`

## 部署

### 1. 准备 NFS 目录

在 NFS 服务端创建以下目录，并确保 Kubernetes 节点可挂载、应用可写入 `db` 目录：

```bash
mkdir -p /data/nfs/k8s/crawl/{db,raw}
```

### 2. 创建命名空间和部署前置 Secret

先创建命名空间；`lifelift-harbor` 和 `nexuscube-tls` 都必须位于 `devops` 命名空间中，并且不纳入 Git 或 Kustomize 管理：

```bash
kubectl apply -f k8s/namespace.yaml
```

安全读取 Harbor 密码并登录。不要把密码写进命令历史、YAML 或仓库：

```bash
read -rs -p "Harbor password: " HARBOR_PASSWORD
printf '\n'
printf '%s' "$HARBOR_PASSWORD" | docker login harbor.lifelift.com.cn:9443 --username cie --password-stdin
```

首次部署时，使用该密码创建镜像拉取 Secret。Deployment 已引用 `imagePullSecrets: lifelift-harbor`，因此必须在应用 Kustomize 清单前完成此步骤：

```bash
kubectl create secret docker-registry lifelift-harbor \
  --docker-server=harbor.lifelift.com.cn:9443 \
  --docker-username=cie \
  --docker-password="$HARBOR_PASSWORD" \
  --namespace=devops
```

使用安全位置存放的证书和私钥创建 TLS Secret，不要提交证书私钥到仓库：

```bash
kubectl create secret tls nexuscube-tls \
  --cert=/secure/path/nexuscube.cn_fullchain.crt \
  --key=/secure/path/nexuscube.cn.key \
  --namespace=devops
```

创建完成后清除当前 shell 中的密码变量：

```bash
unset HARBOR_PASSWORD
```

### 3. 构建并推送镜像

镜像只包含 `server.py`、`static/` 和 `data/manifest.json`；`data/raw/` 与 `data/db/` 会在运行时通过 NFS 挂载提供。

当前 Deployment 使用以下镜像：

```bash
export IMAGE=harbor.lifelift.com.cn:9443/e-commerce/activity-content-review-console:v1
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

如需发布新版本，请使用新的 tag 构建、推送，并同步更新 `k8s/deployment.yaml` 中的 `image` 字段。

### 4. 应用 Kubernetes 清单

确认以下前置条件已满足：

- 集群已安装并启用名为 `nginx` 的 IngressClass。
- DNS 已将 `activity-review-console.nexuscube.cn` 指向 Ingress Controller。
- `devops` 命名空间中已创建包含该域名有效证书的 `nexuscube-tls` Secret。

```bash
kubectl apply -k k8s/
kubectl -n devops rollout status deployment/activity-review-console
kubectl -n devops get ingress activity-review-console
kubectl -n devops get secret lifelift-harbor nexuscube-tls
```

`kustomization.yaml` 已包含 Ingress，因此上述命令会一并应用 Namespace、ConfigMap、Deployment、Service 和 Ingress。

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

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

DNS 和 TLS 就绪后，可通过公网域名验证：

```bash
curl https://activity-review-console.nexuscube.cn/api/health
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

Pod 重建后刷新页面，审核状态仍在，说明 SQLite NFS 数据持久化正常。

## 注意

- `RAW_DATA_ROOT=/app/data/raw` 对应 NFS 挂载目录。
- `DB_PATH=/app/data/db/app.sqlite3` 对应 SQLite NFS 挂载目录。
- `MANIFEST_PATH=/app/data/manifest.json` 默认要求镜像内包含 `data/manifest.json`。
- NFS 服务端须预先创建 `crawl/raw` 和 `crawl/db`；应用进程必须能读取 `raw` 目录并写入 `db` 目录。
- `crawl/raw` 目录内应直接以 `xhs/`、`douyin/` 等平台目录开头。
- SQLite 有写入操作，请保持单副本；需要多副本时应迁移到 MySQL/PostgreSQL。
- 私有镜像仓库需要在 Deployment 中配置对应的 `imagePullSecrets`。
