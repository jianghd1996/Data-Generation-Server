# Data Generation Server

用于服务器端的「素材下载 → 场景组合 → 相机轨迹 → 渲染 → 数据集」管线。
当前实现素材下载与校验，以及单主体的相机环绕渲染。完整三维场景组合和批量渲染尚未实现。

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
dgs-assets download --manifest configs/assets.example.json --root /mnt/DataPart/jianghongda/related_work/Data-Generation-Server/dataset --workers 2
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
dataset/
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

## SSL 证书错误

如果出现 `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`，
可能是代理使用自签 CA，或 Python 环境的 CA 集合缺失。
从服务器/代理管理员取得可信的 PEM CA bundle，传入 `--ca-bundle /path/to/ca.pem`；
也可设置 `DGS_CA_BUNDLE` 或 `SSL_CERT_FILE`。所有子命令及文件下载均使用该配置。

```bash
dgs-assets download --manifest configs/assets.example.json --root /mnt/DataPart/jianghongda/related_work/Data-Generation-Server/dataset --ca-bundle /path/to/ca.pem
```

临时排查可在同一命令末尾加 `--insecure`，仅对本次进程关闭 HTTPS 证书校验。
该模式无法验证服务端身份，建议有正确 CA 后移除；默认仍开启校验。
不支持同时指定 CA bundle 与 `--insecure`。

## 批量下载与离线校验

默认 root 已改为 `/mnt/DataPart/jianghongda/related_work/Data-Generation-Server/dataset`。
可用 `--root` 覆盖。之前下载到别处的素材不会自动移动。

```bash
# 生成 20 个物体模型清单；固定 seed，使同一目录数据下选择可复现
# 若网络证书正常，请移除 --insecure
dgs-assets manifest --type models --limit 20 --seed 42 --resolution 2k --output configs/models.batch.json --insecure

# 可单独生成 HDRI 清单，不要将 HDRI 当成三维场景
dgs-assets manifest --type hdris --query outdoor --limit 5 --seed 42 --output configs/hdris.batch.json --insecure

# 先查看下载计划，再下载
dgs-assets download --manifest configs/models.batch.json --dry-run --insecure
dgs-assets download --manifest configs/models.batch.json --workers 2 --insecure
dgs-assets download --manifest configs/hdris.batch.json --workers 2 --insecure

# 不访问网络、不依赖 Blender；检查文件是否存在、大小、MD5/SHA256及遗留 part
dgs-assets verify
```

`manifest` 从官方目录过滤关键词（ID/元数据），排除尚未发布的素材，按 ID 排序后用固定随机种子抽样。
它生成可编辑的选择清单，不保证每个 ID 都提供所选格式；可用 download --dry-run 确认。
关键词是子串匹配，不是语义搜索。上游目录变化时抽样也可能变化，因此应保存生成的清单。
物体、纹理、HDRI 分开建清单；完整三维场景和人物仍通过 direct 清单加入。

`verify` 默认生成 dataset/verification-report.json；无完整素材、文件损坏、元数据异常或遗留 .part 时退出码为 1。
报告只检查已存在的 asset.json，不证明某个下载清单的所有资产均已完成；下载失败还应查看 download-report.json。
发现损坏后重新执行原下载清单即可修复。不自动删除素材。
兼容旧版 asset.json 的资产目录相对路径，新版额外保存 dataset_path，方便渲染批量读取。
校验阶段不会检查 Blender 加载、贴图绑定或模型视觉质量，这些需后续试渲染。

下载时每个文件开始、结束以及传输期间约每秒输出一行进度：文件名、百分比、MiB 和 MiB/s。
并发下载的进度按文件名区分；服务器日志中保留每行，不需要交互终端。大小未知时显示 `? %`。
已验证的文件显示 `[skip]`。进度写到 stderr；最后的 100% 仅代表传输结束，随后仍需校验。

## 单样例环绕渲染

依赖：Linux Blender **4.2–4.5**（推荐官方下载的 4.5 LTS 二进制）与 ffmpeg。
Blender 是独立程序，不要在普通 Python 环境 pip install bpy 来替代此启动流程。
Blender 5 的合成器 API 暂未支持。下载阶段的 Python 环境不必装 torch。

```bash
# 更新后重新安装，注册新增的 dgs-render 命令
python -m pip install -e .
blender --version
ffmpeg -version

# 先渲染 3 帧、640×360，检查加载、贴图、GPU 与输出
CUDA_VISIBLE_DEVICES=4 dgs-render --frames 3 --width 640 --height 360 --samples 16 \
  --output /mnt/DataPart/jianghongda/related_work/Data-Generation-Server/dataset/renders/horse_smoke

# 通过后再做 81 帧、720P、90° 环绕
CUDA_VISIBLE_DEVICES=4 dgs-render --frames 81 --samples 32 --sweep 90 \
  --output /mnt/DataPart/jianghongda/related_work/Data-Generation-Server/dataset/renders/horse_orbit_90
```

默认从 root 下的 `horse_statue_01` 与 `abandoned_factory_canteen_01` 的 asset.json 找到主文件。
旧下载位于其他目录时用 `--root /实际素材根目录`；输出仍可独立通过 --output 指定。
Blender 没在 PATH 中时加 `--blender /完整路径/blender`。
默认 CUDA，可显式选 `--device OPTIX` 或 `--device CPU`。没有可用 GPU 时明确失败，不静默切换 CPU。
`CUDA_VISIBLE_DEVICES` 在启动前指定 GPU；不要与下载命令的 workers 混淆。
不编码视频时用 `--no-video`，此时无需 ffmpeg，首帧保留为 rgb/rgb_0001.png。

输出包含：

- `video.mp4`：RGB 环绕视频；`image.jpg`：首帧。
- `rgb/rgb_0001.png` 等：无损帧。
- `mask/mask_0001.png` 等：白色主体、黑色背景，包含抗锯齿边界。
- `depth/depth_0001.exr` 等：32 位 Blender Z pass；不是直接可视化的灰度图片。
- `cameras.json`：K、每帧 OpenCV 坐标约定的 c2w/w2c、时间和文件名。
- `scene.blend`、`render-config.json`、`render-report.json`、`prompt.txt`。
- `SUCCESS.json`：渲染帧齐全且编码成功后生成。

主体按包围盒最长边归一化到 2 个场景单位、底部贴地；物体与灯光保持静止，仅相机移动。
相机保持目标中心，默认固定半径 4.5、仰角 12°、焦距 35mm、从 -90° 开始扫过 90°。
可调 `--subject-size`、`--radius`、`--elevation`、`--start-angle`、`--sweep`、`--focal-mm`。
360° 时首尾重复视角（非无缝循环编码策略）；实际构图需查看 smoke 图片后调节。
深度单位是归一化后的场景单位，Z pass 为可见表面的相机距离，背景可能为很大数值。
透视内参采用水平 sensor fit、方形像素；相机坐标 X 右/Y 下/Z 前，世界坐标 Z 上。
场景为大地面 + HDRI，不是完整食堂环境；地面有三维视差，HDRI 只提供远景/光照。

支持 .blend/.glb/.gltf/.fbx/.obj 单主体。blend 中所有几何作为一个主体加载，原相机/灯光关闭；
不会自动从含多个场景物体的 blend 中识别主角。导入主体冻结动画，人物使用已摆好姿势的素材。
贴图缺失时生成失败报告并停止；不生成粉色贴图视频。合成器一次渲染同时输出 RGB/mask/depth。
输出目录非空时拒绝覆盖；改目录或使用 --overwrite（删除管线已知输出文件，不删除其他文件）。
启动脚本先检查素材、Blender、ffmpeg，再调用 Blender。Blender 错误会传回非零退出码。
这里尚未在真实 Blender/GPU 上试渲染，需用 3 帧 smoke 命令验证版本与画面。
