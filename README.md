# Data Generation Server

用于服务器端的「素材下载 → 场景组合 → 相机轨迹 → 渲染 → 数据集」管线。
当前实现第一阶段：素材检索、清单下载、校验与来源记录。渲染阶段尚未实现。

## 安装与开始

Python >= 3.10，下载阶段无需 GPU、Blender 或第三方运行时依赖。

```bash
git clone https://github.com/jianghd1996/Data-Generation-Server.git
cd Data-Generation-Server
python -m pip install -e .

# 查询可用素材；返回 ID、名称及元数据
dgs-assets search --type models --query statue --limit 10
dgs-assets search --type hdris --query outdoor --limit 10 --output catalog.json

# 查询某个素材实际可用的格式和分辨率
dgs-assets files horse_statue_01

# 只解析下载计划，不写入文件（仍访问素材 API）
dgs-assets download --manifest configs/assets.example.json --dry-run

# 下载；同一命令可以重新运行，自动检查并跳过完整文件
dgs-assets download --manifest configs/assets.example.json --root /mnt/DataPart/jianghongda/dataset/orbit/assets --workers 2
```

示例 ID 来自官方 API 文档，可能随上游调整；若格式不可用，请用 `files` 查看后修改配置。
默认 2k 贴图、两个并发素材；每个素材内部按顺序下载。不要同时运行多个下载进程写入同一 root。
下载支持系统 HTTP_PROXY/HTTPS_PROXY 环境变量，网络超时 60 秒，失败最多尝试四次。

## 素材清单

JSON 顶层包含 `version: 1` 与 `assets` 数组。

Poly Haven：

```json
{"provider":"polyhaven","id":"horse_statue_01","kind":"models","resolution":"2k","format":"blend"}
```

支持 models、textures、hdris；HDRI 使用 hdr/exr，模型使用 API 实际提供的 blend/gltf/fbx 等格式。
模型/材质主文件的 `include` 依赖会一并下载，保持官方相对路径。
不会静默降低分辨率或替换格式；不存在的组合明确报错。
HDRI 不是完整三维场景，不能替代有近景视差的几何环境。

人物、完整场景或其他来源的合法下载直链：

```json
{
  "version": 1,
  "assets": [{
    "provider": "direct",
    "id": "standing_person_001",
    "kind": "people",
    "source_url": "https://example.com/asset-page",
    "license": "填写该素材的实际许可名称或链接",
    "files": [{
      "url": "https://example.com/person.glb",
      "path": "person.glb"
    }]
  }]
}
```

以上 example.com 是格式示意，需替换为真实 URL。可选文件字段：`size`（字节）、`sha256`、`md5`。
推荐 GLB；FBX/OBJ/GLTF 等外部贴图和材质文件须逐项列入 files 并保持相对路径。
ZIP 文件只下载，不自动解压。不接入登录网站的页面爬取；Mixamo/Fab/Sketchfab 等需先取得允许下载的链接。
短期签名链接过期后更新清单即可；目前不支持自定义鉴权头或自动刷新令牌。

## 输出及可恢复性

```text
data/assets/
  models/polyhaven/horse_statue_01/
    horse_statue_01_2k.blend
    textures/...
    asset.json
  hdris/polyhaven/abandoned_factory_canteen_01/...
  people/direct/standing_person_001/...
  download-report.json
```

`asset.json` 记录原始配置、来源、许可、官方元数据、文件相对路径和 SHA256。
`download-report.json` 为本次运行成功/失败的汇总，不是累积索引；每个素材的 asset.json 可供后续渲染读取。
文件先写入 `.part`，校验完成再原子替换正式文件。断点续传以 ETag/Last-Modified 和 If-Range 绑定服务端版本；
服务端忽略 Range 时重新下载。已下载文件通过本地 SHA256 receipt 检查，损坏时重新下载。
上游有 MD5/大小时额外核验；直链没有上游校验值时，本地 SHA256 用于后续完整性检查，不代表上游真实性认证。
单个素材失败不阻断其他素材，最终退出码为 1；重新运行清单即可重试。
成功素材的 asset.json 仅在全部依赖下载完成后生成。

## 测试

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

测试使用模拟 HTTP 响应，无需外网，覆盖续传、服务端忽略 Range、校验失败、路径安全及模型贴图依赖。

## 来源与许可

Powered by Poly Haven — https://polyhaven.com/

官方 API：https://github.com/Poly-Haven/Public-API
API 条款：https://github.com/Poly-Haven/Public-API/blob/master/ToS.md
请求使用项目专属 User-Agent。Poly Haven 资产为 CC0；其他素材许可由清单提供并随资产保存。
下载代码不自动判断训练或再分发权限。素材不提交到 Git 仓库。
