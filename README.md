# Data Generation Server

在带 NVIDIA GPU 的 Linux 服务器上，把静止物体或人物放入三维环境，沿可控相机轨迹渲染视频与几何标注。

项目使用 **Blender Cycles + Python**，涵盖素材下载、完整性校验、素材审核、场景组合、球面轨迹、视频编码和多 GPU 批量调度。适合相机控制、视角扩充、三维重建及合成数据实验。

> 最小使用流程：下载一个主体和一个 HDRI → 渲染少量帧确认素材 → 检查素材目录 → 生成组合计划 → 多卡执行。

## 功能与范围

| 部分 | 当前支持 |
| --- | --- |
| 素材 | Poly Haven 模型/材质/HDRI；Renderpeople 免费静止人物；其他合法 HTTP(S) 直链或本地人物 ZIP |
| 下载 | 并发、断点续传、大小与校验值检查、失败重试、完整文件跳过、进度输出 |
| 环境 | 地面加 HDRI、程序化庭院、完整外部 `.blend` 场景 |
| 主体 | `.blend`、`.glb/.gltf`、`.fbx`、`.obj`；自动缩放、居中、贴地与朝向调整 |
| 相机 | 球面左右镜像双环轨迹、普通环绕；始终朝向球心 |
| 景别 | 物体近/中/远；人物胸部—头部、膝盖—头部、全身 |
| 输出 | RGB、主体 mask、深度 EXR、相机内外参、视频、首帧、配置与报告 |
| 批量 | 主体×场景×HDRI组合；每组合近中远各一横一竖；固定随机种子 |
| 调度 | 指定多张 GPU，每卡一个任务；成功任务跳过，失败任务可重新渲染 |

场景、模型与人物保持静止，仅相机运动。暂不支持自动寻找落脚点、碰撞避让、骨骼语义检测、动态人物、逐帧渲染恢复或每卡多个并行任务。

## 1. 环境与安装

- Linux；项目 Python **3.10+**。
- Blender **4.2–4.5**，推荐 4.5 LTS。当前合成器代码不支持 Blender 5。
- NVIDIA GPU 与兼容驱动。默认 Cycles CUDA，也可指定 OPTIX 或显式 CPU。
- ffmpeg：用于 H.264 MP4 编码和首帧 JPEG；仅渲染图片可用 `--no-video`。
- 项目 Python 运行时只使用标准库，无需安装 torch 或 diffusers。

```bash
git clone https://github.com/jianghd1996/Data-Generation-Server.git
cd Data-Generation-Server
python -m pip install -e .

blender --version
ffmpeg -version
nvidia-smi
```

从 [Blender 官方下载目录](https://download.blender.org/release/Blender4.5/)取得与你系统匹配的 Linux 安装包，解压即可使用，无需把 Blender 装进 Python 环境。
Blender 不在 PATH 中时，为渲染命令传入 `--blender /absolute/path/to/blender`。

项目提供五个命令：

| 命令 | 用途 |
| --- | --- |
| `dgs-assets` | 查找素材、生成下载清单、下载和离线校验 |
| `dgs-scenes` | 下载并解压官方完整场景包 |
| `dgs-people` | 下载/导入人物 ZIP，安全解压并列出模型路径 |
| `dgs-render` | 单样例场景组合、轨迹渲染、标注与视频输出 |
| `dgs-dataset` | 素材目录审核、数量检查、生成计划、多卡执行 |

### 路径约定

以下教程使用可移植的项目内数据目录：

```bash
export DGS_ROOT="$PWD/dataset"
export DGS_BLENDER="/absolute/path/to/blender"
```

**请将 `DGS_BLENDER` 改成实际可执行文件。**
`DGS_ROOT`/`DGS_BLENDER` 用于本 README 和辅助脚本；CLI 需要显式传 `--root`/`--blender`。
未指定 `--root` 时，代码默认使用原实验服务器路径：

```text
/mnt/DataPart/jianghongda/related_work/Data-Generation-Server/dataset
```

`--root` 控制素材读取/下载位置，`--output` 控制渲染结果位置，两者可以不同。素材和生成结果不提交到 Git。

## 2. 最小样例：下载并渲染

### 2.1 下载物体与 HDRI

仓库的 `configs/assets.example.json` 包含一个马雕像及一个 HDRI。

```bash
dgs-assets download --manifest configs/assets.example.json --root "$DGS_ROOT" --workers 2
```

素材上游格式变化时先用 `dgs-assets files horse_statue_01` 查询实际可用选项。
下载成功会显示 `OK <asset-id>`，模型引用的贴图会一起下载并保持相对目录结构。

### 2.2 先检查三帧

```bash
CUDA_VISIBLE_DEVICES=0 dgs-render \
  --root "$DGS_ROOT" --blender "$DGS_BLENDER" \
  --model-id horse_statue_01 --hdri-id abandoned_factory_canteen_01 \
  --environment courtyard --trajectory orbit --sweep 60 \
  --frames 3 --width 640 --height 360 --orientation landscape \
  --samples 16 --no-video \
  --output "$DGS_ROOT/renders/horse_smoke"
```

查看 `horse_smoke/rgb/`：确认贴图、主体朝向、位置、构图和光照。输出目录非空时拒绝覆盖，换目录或显式使用 `--overwrite`。

### 2.3 生成121帧视频

```bash
CUDA_VISIBLE_DEVICES=0 dgs-render \
  --root "$DGS_ROOT" --blender "$DGS_BLENDER" \
  --model-id horse_statue_01 --hdri-id abandoned_factory_canteen_01 \
  --environment courtyard \
  --trajectory figure8 --theta 30 --phi 5 --frames 121 \
  --width 1280 --height 720 --orientation random --seed 42 \
  --samples 32 \
  --output "$DGS_ROOT/renders/horse_figure8"
```

视频为 `horse_figure8/video.mp4`。24 fps 时121帧约5.04秒。
默认随机选1280×720或720×1280，seed相同会复现方向；`--orientation landscape/portrait` 可固定方向。

已有衣柜与 HDRI 的用户，也可运行 `bash scripts/test_figure8.sh`。该脚本使用 `chinese_cabinet`、自动查找已下载 HDRI，并读取 `DGS_ROOT`/`DGS_BLENDER`；可通过 `DGS_GPU`、`DGS_THETA`、`DGS_PHI`、`DGS_SEED`、`DGS_ORIENTATION`、`DGS_OUTPUT` 覆盖参数。

## 3. 素材下载与扩充

### Poly Haven

Powered by Poly Haven — [polyhaven.com](https://polyhaven.com/)

```bash
# ID和元数据；query是子串匹配，不是语义检索
dgs-assets search --type models --query statue --limit 10
dgs-assets search --type hdris --query outdoor --limit 10

# 查格式、分辨率和依赖
dgs-assets files horse_statue_01

# 固定随机种子抽样，保存一次清单后重复使用
dgs-assets manifest --type models --limit 24 --seed 42 --resolution 2k \
  --output configs/models.batch.json

dgs-assets download --manifest configs/models.batch.json --root "$DGS_ROOT" --dry-run
dgs-assets download --manifest configs/models.batch.json --root "$DGS_ROOT" --workers 4
```

`--type` 支持 `models`、`hdris`、`textures`。HDRI默认HDR，模型/材质默认Blender格式；可用 `--format` 指定实际支持的格式。
清单生成不保证每个素材都提供选定格式，`--dry-run` 会访问API解析下载计划，但不写素材文件。上游目录变化时抽样可能变化，因此保留原清单。

辅助扩充脚本：

```bash
bash scripts/expand_assets.sh
```

它为物体和HDRI各准备24个候选，并下载当前Renderpeople免费样例，最后生成库存报告。已有清单保留供重试。
**该脚本默认加 `--insecure`，是原代理环境的兼容设置**；网络证书正常的用户应移除它，或改为自定义CA。
不要同时启动多个下载进程写入同一数据根目录。下载和GPU渲染可在不同终端同时进行。

### 人物

```bash
# 已确认的官方免费人物GLB ZIP；下载后自动解压
dgs-people --provider renderpeople --root "$DGS_ROOT"
```

命令列出的模型路径可以直接传给 `dgs-render --model`。默认文件位于 `people/direct/renderpeople_free_posed/extracted/`。

[Humano3D 免费样例](https://humano3d.com/free-sample/)目前需要选择格式并领取，未接入购物车或登录流程。
领取Blender、GLB或OBJ/FBX包后：

```bash
dgs-people --provider humano3d --archive /absolute/path/sample.zip \
  --id humano_sample02 --root "$DGS_ROOT"

# 也支持已领取的真实ZIP下载链接
dgs-people --provider humano3d --url '实际ZIP文件链接' \
  --id humano_sample03 --root "$DGS_ROOT"
```

**多个素材包请使用不同 `--id`**，避免替换之前解压的目录。默认Renderpeople入口不表示已提供十余个独立人物。
ZIP解压保留完整目录结构，检查CRC，拒绝路径越界、符号链接及超过20GiB的归档。普通 `dgs-assets` 下载ZIP时不会自动解压。

### 通用直链清单

```json
{
  "version": 1,
  "assets": [{
    "provider": "direct",
    "id": "scene_room01",
    "kind": "scenes",
    "source_url": "https://example.com/asset-page",
    "license": "填写该素材实际许可名称或链接",
    "files": [{
      "url": "https://example.com/environment.blend",
      "path": "environment.blend"
    }, {
      "url": "https://example.com/color.png",
      "path": "textures/color.png"
    }]
  }]
}
```

`example.com`仅为格式示意，需换成真实文件直链。每个文件可额外提供 `size`（字节）、`sha256`、`md5`。
`kind` 支持 `models/people/scenes/hdris/textures`，`direct` 素材必须记录来源和许可。ZIP之外的外部依赖须逐项列入清单。
不支持登录页面下载、自定义鉴权头或自动刷新签名链接。私密下载链接不要提交到Git。

### 续传、重试与校验

重新执行**同一下载清单**即可恢复：

- 完整且校验通过的文件显示 `[skip]`；损坏文件重新下载。
- 未完成文件保存为 `.part`。服务端有ETag/Last-Modified且支持Range时尝试续传。
- 服务端不支持续传或版本变化时重新下载；HTTP416会重启该文件下载。
- 网络超时60秒，每个文件最多尝试4次。最终失败不阻断其他素材，整个命令退出码为1。
- 正式文件在传输和校验后原子替换。进度100%只表示传输结束，`OK`表示整个素材处理成功。

```bash
dgs-assets verify --root "$DGS_ROOT"
```

`verification-report.json` 检查已有 `asset.json` 的文件、大小、校验值和残留 `.part`。它不验证Blender加载或视觉质量，也不证明清单中未出现的素材已经下载。
`download-report.json`只记录最近一次下载调用，不是所有调用的累计历史。来源、许可和SHA256另存于每个素材的 `asset.json`。

## 4. 三维环境与主体放置

| 选项 | 行为 |
| --- | --- |
| `--environment studio` | 大面积纯色地面加HDRI，适合模型加载检查；地面可能遮住HDRI下半部分 |
| `--environment courtyard` | 程序化铺地、围墙、立柱和花坛；HDRI用于天空和照明 |
| `--scene /path/environment.blend` | 读取完整活动场景，保留环境几何、材质、灯光和world；不添加地面 |

**HDRI不是三维场景**：它提供光照和远景，没有附近树木、建筑的几何视差。
当前12个 `--scene-preset` 庭院选项是同一种程序化环境的布局/色调变体，不是12个独立高质量场景资产。数量检查将它们归为一个identity。

```bash
CUDA_VISIBLE_DEVICES=0 dgs-render \
  --root "$DGS_ROOT" --blender "$DGS_BLENDER" \
  --model /absolute/path/person.glb \
  --scene /absolute/path/environment.blend \
  --subject-position 0 0 0 --subject-heading 0 \
  --subject-kind person --shot far \
  --frames 121 --output "$DGS_ROOT/renders/person_in_scene"
```

外部场景无需另配HDRI；要覆盖原world，用 `--hdri /absolute/path/light.hdr`，此模式不使用 `--hdri-id`。
原场景文件不修改，只在输出目录保存组合后的 `scene.blend`。
原相机、合成器、分辨率和色彩管理会由本管线替换；对象动画清除，但特殊驱动、节点动画和物理模拟应先处理成静态素材。
贴图应打包或保持正确相对路径。特殊插件、模拟缓存和外部Geometry Nodes依赖需要自行准备。

`--subject-size`将主体最长边归一化到目标长度，默认2个场景单位；环境本身不缩放。
`--subject-position X Y Z` 是底面/脚底中心，`--subject-heading`是绕Z轴的角度。
不会自动识别一个复杂模型文件中的主角，导入文件中全部几何会作为主体。请先检查三帧，确认空地、模型朝向和相机路径。

## 5. 球面轨迹与景别

### 左右镜像双环

默认 `--trajectory figure8 --frames 121 --theta 30 --phi 5`。
相对于初始方位角/仰角，各节点为：

| 环 | 节点偏移 `(方位角, 仰角)` |
| --- | --- |
| 右 | `(0,0) → (0,+φ) → (+θ,+φ) → (+θ,-φ) → (0,-φ) → (0,0)` |
| 左 | `(0,0) → (0,+φ) → (-θ,+φ) → (-θ,-φ) → (0,-φ) → (0,0)` |

这是十段指定动作形成的镜像双环，不是正弦8字曲线。121帧对应120个时间间隔，每段12个间隔；第1/61/121帧回到相同位姿。
转角使用五次缓入缓出，平滑停顿，不是全程匀速。相机半径固定，始终朝球心，无roll。
默认 `--start-angle -90 --elevation 12`，φ=5时实际仰角为7°–17°。模型正面需用heading或start-angle调整。
普通环绕用 `--trajectory orbit --sweep 90`。360°环绕首尾重复视角。

### 近、中、远景

| 主体 | near | medium | far |
| --- | --- | --- | --- |
| 物体 | 完整主体，目标画面比例约85% | 约64% | 约40% |
| 人物 | 胸部—头部 | 膝盖—头部 | 原4.5球面距离，全身中心 |

单例通过 `--subject-kind object/person --shot near/medium/far` 选择。
默认 `--shot manual` 保留固定半径和全主体中心；批量计划显式生成三档。
人物近/中景按包围盒高度比例估计胸部0.65、膝盖0.28，将取景区域中心作为球心，再计算距离。
可用 `--person-chest`/`--person-knee` 修正，也可在人物catalog条目中设置 `chest`/`knee`。
抬手、坐姿、道具和特殊衣物会影响包围盒，需人工检查。画面裁切随角度可能变化；不是解剖学检测。
物体的宽高都会约束距离。横竖屏保持短边视场角；近/中景按各自画幅重算距离。
实际 `framing.target` 和 `effective_radius` 写入相机文件与报告。

常用默认参数：

| 参数 | 默认值 |
| --- | --- |
| 帧数 / 帧率 | 121 / 24 fps |
| 尺寸 | 1280×720，按方向交换 |
| 方向 / seed | random / 42 |
| Cycles samples / device | 32 / CUDA |
| θ / φ | 30° / 5° |
| radius / elevation | 4.5 / 12° |
| start-angle / focal-mm | -90° / 35mm参考焦距 |

所有参数可通过 `dgs-render --help` 查询。

## 6. 检查素材与生成组合计划

### 库存及审核

```bash
dgs-dataset inventory --root "$DGS_ROOT" --minimum 11
```

生成 `catalog.json`、`coverage-report.json`，分别列出 objects、people、scenes、backgrounds。
数量不足退出码为1，这表示覆盖缺口，不代表下载全部失败。
候选计数、unique_identities、approved、procedural和external分别报告；文件存在不等于视觉合格。

审核时修改 `catalog.json`：

```json
{
  "id": "person01",
  "path": "/absolute/path/person.glb",
  "enabled": true,
  "review": "approved",
  "identity": "person01",
  "heading": 0,
  "size": 2,
  "chest": 0.65,
  "knee": 0.28,
  "notes": "已检查朝向和近中远裁切"
}
```

以上是 `people` 数组中的单条示意，不是完整catalog文件。
不合适的条目设 `enabled=false`。同一人的不同格式、LOD、换色或姿态填写相同identity，避免虚增人数。
再次inventory保留审核信息；自动去重不能代替人物身份检查。

外部场景放进 `dataset/scenes/` 后重新扫描，或在 `scenes` 数组手动登记绝对路径和主体位置：

```json
{"id":"room01","path":"/absolute/path/room.blend","position":[0,0,0],"enabled":true,"review":"approved"}
```

扫描保留仍存在的手动登记外部素材。新增素材后需重新生成计划才能使用。

### 固定抽样组合

```bash
dgs-dataset plan --catalog "$DGS_ROOT/catalog.json" \
  --output "$DGS_ROOT/render-plan.json" \
  --combinations-per-subject 1 --seed 42
```

每个主体生成近中远×横竖屏共6条视频；默认每条独立抽取场景与HDRI，方向之间也可不同。
`--combinations-per-subject 3`可扩展为每个主体18条；正式数据建议加 `--approved-only`。
默认允许待审核候选，方便先生成检查样例。

`--all-combinations`枚举全部，视频数量为：

```text
(物体数 + 人物数) × 场景数 × HDRI数 × 3景别 × 2方向
```

例如22个主体、12个场景、12个HDRI会生成19,008条视频。先确认计划规模再执行。
计划保存绝对素材路径、组合、方向、输出目录和settings，可手工修改全局frames/theta/phi/samples/radius。
保存不同计划文件可保留实验配置；不要依靠重新随机抽样恢复旧实验。

## 7. 单卡和多卡执行

先测试一个组合的六条视频：

```bash
CUDA_VISIBLE_DEVICES=0 dgs-dataset run --plan "$DGS_ROOT/render-plan.json" \
  --blender "$DGS_BLENDER" --limit 6
```

确认后四卡执行：

```bash
dgs-dataset run --plan "$DGS_ROOT/render-plan.json" \
  --blender "$DGS_BLENDER" --gpus 0,1,2,3 --retry-incomplete
```

- 每个GPU一个Blender进程；完成后从共享队列领取下一条。
- `--gpus`是物理卡编号，覆盖子进程的CUDA_VISIBLE_DEVICES；无需额外设置该变量。
- `--limit`是所有卡合计的待执行任务数，不是每卡数。
- 成功且配置一致的任务跳过；失败不阻断其他任务。
- `--retry-incomplete`覆盖未完成或配置变化任务的已知管线输出，从头重渲染；不续渲染单帧。
- 输出路径必须唯一，避免启动两个调度器写同一计划。
- 多卡完整日志分文件保存；终端显示任务开始/完成/失败。

报告和日志在计划旁：`render-plan.run-report.json`、`render-plan.run-report.logs/`。
报告记录任务ID、GPU、日志路径和失败原因。

目前每卡只跑一个任务，没有 `--jobs-per-gpu` 参数。
显存占用少不代表计算空闲，应结合GPU-Util及同样任务量的总耗时判断瓶颈。
多卡也会增加CPU、内存与磁盘负载；单条视频不保证按GPU数量提速。

## 8. 输出目录与标注

数据根目录约定：`models/`、`people/`、`scenes/`、`hdris/`、`textures/`为素材，`renders/`为结果。
每条渲染输出：

| 文件 | 内容 |
| --- | --- |
| `video.mp4` | H.264、yuv420p、CRF18；完整帧序列直接编码 |
| `image.jpg` | RGB首帧；`--no-video`时不生成 |
| `rgb/rgb_0001.png` | RGB PNG序列 |
| `mask/mask_0001.png` | 白色可见主体、黑色背景、抗锯齿边界 |
| `depth/depth_0001.exr` | 32位Blender Z pass，非显示用灰度图 |
| `cameras.json` | K、每帧c2w/w2c、时间、角度、路径与framing |
| `render-config.json` | 输入参数和实际横竖屏尺寸 |
| `render-report.json` | Blender版本、GPU、耗时、包围盒、归一化与取景信息 |
| `scene.blend` | 最终组合场景 |
| `prompt.txt` | 简单描述模板，非自动详细caption |
| `SUCCESS.json` | 完整帧检查和可选编码结束后生成的完成标记 |

坐标约定：世界坐标为Blender **Z向上**；导出相机坐标为OpenCV **X右、Y下、Z前**。
c2w把相机点变换到世界，w2c为其逆。K采用水平sensor fit和方形像素，焦距按实际画幅设置。
深度为Blender Z pass的可见表面相机距离，单位是归一化后的场景单位；背景可能为很大值。
它不保证等同于CV相机轴向z，使用时应按距离图处理并屏蔽背景。
主体mask只包含实际可见部分，不包含被场景遮挡的身体，也不包含地面阴影。

## 9. 常见问题

| 问题 | 处理 |
| --- | --- |
| `Blender executable not found` | 传 `--blender /实际路径/blender`；检查 `blender --version` |
| HDRI/模型的 `asset.json` 不存在 | 确认下载root与渲染root一致；用正确ID或 `--model`/`--hdri`完整路径 |
| 复制示例后找不到 `configs/...json` | 在仓库根目录执行，或使用绝对清单路径 |
| `CERTIFICATE_VERIFY_FAILED` | 从管理员取得可信CA，用 `--ca-bundle /path/ca.pem`，或DGS_CA_BUNDLE/SSL_CERT_FILE |
| 临时排查证书问题 | 下载命令显式加 `--insecure`；仅本次进程关闭服务端身份验证 |
| 下载慢或读超时 | 原清单重跑即可续传；尝试workers=4，实际速度取决于网络 |
| ZIP不是有效归档 | 链接可能返回登录页或错误页；使用真实ZIP链接或本地领取文件 |
| 背景下半部分纯色 | studio地面遮住HDRI；改courtyard或完整三维场景 |
| 人物裁切/朝向不合适 | 调heading、chest/knee、size，先渲染少量帧检查 |
| 输出目录非空 | 新输出路径，单例 `--overwrite`，批量 `--retry-incomplete` |
| 多卡终端看不到逐帧日志 | 查看run-report记录的独立log文件 |
| 缺GPU或初始化失败 | 检查驱动、Blender构建和GPU编号；显式CPU可用于诊断 |

自定义CA或关闭校验选项用于下载命令，渲染命令不需要它们。
下载可以使用系统HTTP_PROXY/HTTPS_PROXY；不能把素材网页URL当成文件URL。

## 10. 开发与验证

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```

测试覆盖下载恢复、校验、路径安全、ZIP解压、轨迹节点与镜像、横竖屏、景别计算、组合数量、多GPU队列和隔离。
HTTP、Blender启动及GPU分配测试使用模拟，不代替真实服务器渲染。
当前使用者已在服务器验证物体、人物、庭院和121帧轨迹；新素材仍应先做加载/视觉检查。

源码入口：

| 文件 | 职责 |
| --- | --- |
| `assets.py` | 官方API、清单解析、下载、完整性检查 |
| `people.py` | 人物包下载与安全解压 |
| `render.py` | 参数检查、Blender启动、编码 |
| `blender_orbit.py` | Blender内导入、场景、相机、标注和渲染 |
| `trajectory.py` / `shots.py` | 轨迹与景别计算 |
| `dataset.py` | 库存审核、任务计划、单卡/多卡调度 |

提交问题时建议附：commit、Blender版本、GPU/驱动、完整命令、报错日志及相关配置。
下载签名链接、账号信息和私密路径可先脱敏。提交代码不要包含数据、模型或渲染输出。

## 素材来源与许可

- [Poly Haven](https://polyhaven.com/)资产为CC0；实时API使用需遵循[API条款](https://github.com/Poly-Haven/Public-API/blob/master/ToS.md)，本项目使用专属User-Agent并注明来源。
- [Renderpeople](https://renderpeople.com/free-3d-people/)与[Humano3D](https://humano3d.com/free-sample/)使用各自供应商许可，不是CC0。
- 本项目下载并记录来源，不自动判断训练、公开数据集或素材再分发权限。免费渲染素材不等于允许任意训练用途。
- 仓库不附带第三方素材；发布生成数据前请核对相应许可。

## 下载完整场景并重新随机环境

```bash
# 六个官方完整场景包（可能占用较大磁盘；完整包默认解压上限100GiB）
dgs-scenes --root "$DGS_ROOT" --insecure
# 或只下载部分
dgs-scenes --root "$DGS_ROOT" --ids hidden_alley pine_forest the_shed --insecure

dgs-dataset inventory --root "$DGS_ROOT"
```

来源：https://polyhaven.com/collections ，包含 moon/namaqualand/verdant_trail/hidden_alley/pine_forest/the_shed。
支持断点下载；成功解压可复用。失败报告在scene-download-report.json。
每包保存 scene-registration.json，列出候选blend；默认选路径最浅的blend作为主场景。
请检查候选，必要时修改 catalog.scenes 的path和position。默认为世界原点，不能保证是空地。
包中的素材blend不会全部当作独立场景计数。归档与全部贴图一起保留，可能需要数十GiB磁盘。
脚本只验证下载/解压，不保证每个场景适配Blender4.x或具备完整第三方插件依赖。

```bash
# 仅采用下载/手动导入的真实场景，不再抽courtyard变体；新目录避免覆盖旧实验
dgs-dataset plan --catalog "$DGS_ROOT/catalog.json" \
  --output "$DGS_ROOT/render-plan-scenes-v2.json" \
  --render-root "$DGS_ROOT/renders/scenes-v2" \
  --combinations-per-subject 1 --environment-sampling per-video \
  --external-scenes-only --seed 20261009

dgs-dataset run --plan "$DGS_ROOT/render-plan-scenes-v2.json" \
  --blender "$DGS_BLENDER" --gpus 0,1,2,3 --limit 6
```

默认per-video为每条独立抽取环境；可能随机重复，不承诺每六条互不相同。
`--environment-sampling per-combination`恢复旧模式，六条共用一个环境。
`--all-combinations`仍按全部组合枚举，不启用随机替换。
相机轨迹、近中远计算、主体参数和横竖屏不变；需要重新plan才能改变旧计划里的固定环境。
检查第一批视频后，去掉limit运行全部。落脚点在catalog中修改后需重新生成计划。


### 批量补充人物

旧版默认人物下载只有一个新款 GLB。现在可以下载官方公开的新款 GLB 和经典静态 OBJ 包：

```bash
dgs-people --batch --root "$DGS_ROOT" --insecure
dgs-dataset inventory --root "$DGS_ROOT"
```

免费包不保证提供 11 个不同人物；不同格式、LOD、衣服配色不能当成不同人物。
经典包的材质和导入需先渲染检查。单包失败不会阻止其他包；报告为 `people-batch-report.json`。
重新运行会跳过校验通过的下载，并复用相同 ZIP 的解压结果。未完成下载沿用条件续传。

从官方获取多个 ZIP 后，一次导入整个目录，保留贴图：

```bash
dgs-people --provider humano3d --archive-dir /path/to/authorized-zips --root "$DGS_ROOT"
```

也可使用 `--manifest configs/people.batch.json`，格式如下；archive 相对 JSON 所在目录解析。
每个包必须有唯一 id，以及 url（真实 ZIP 下载链接）或 archive 二选一：

```json
{"assets": [{"id": "humano_pack_01", "provider": "humano3d", "archive": "downloads/people.zip", "source_url": "https://humano3d.com/", "license": "Vendor license; retain packaged terms"}]}
```

不会自动进行需要账户/结账的人物下载；使用已获取的链接或 ZIP。导入后重新 inventory，
检查 catalog 的 identity/review，确认不同人物数量。下载包数量不等于人物数量。

人物包支持最多四层内嵌 ZIP 自动展开，共享 20 GiB 解压上限；重跑批量命令会复用已下载的外层 ZIP。

人物扫描会合并同目录中相同名称的 OBJ/FBX 和 `_30k`、`_100k` 等网格精度版本。
经典包的母子合体仍是一项可渲染素材；identity 需人工审核，不代表单个自然人。


### 更多 Renderpeople 人物

`--batch` 还会下载 Posed Plus 静态样本。该官方外层 ZIP 含多种软件格式，约 1 GiB 以上；
解压时只展开其中 OBJ/FBX/GLB 子包，避免导入同一人物的多个软件版本。
需要额外三个带骨骼人物（Eric、Carla、Claudia）可使用：

```bash
dgs-people --batch --include-rigged --root "$DGS_ROOT" --insecure
dgs-dataset inventory --root "$DGS_ROOT" --minimum 11
```

骨骼人物是 A/T 等参考姿态，扫描优先选择 Z-up A-pose FBX，合并其他坐标轴/平台版本；
渲染前检查材质及姿态，按需在 catalog 中禁用。新增包仍不保证达到 11 个不同人物素材。


### 优先下载小场景

新增 Blender 官方示例来源（Classroom 教室、Barcelona Pavilion 建筑），默认单包下载上限 150 MiB：

```bash
dgs-scenes --provider blender --root "$DGS_ROOT" --max-download-mib 150 --insecure
dgs-dataset inventory --root "$DGS_ROOT" --minimum 11
```

下载前用一字节 Range 请求检查完整大小；超出上限或无法确认大小时失败，不下载完整包。
下载器同时检查响应大小和写入字节数。Classroom 标注 CC0；Barcelona Pavilion 按来源 CC-BY
记录作者，保留下载包条款。两个场景不能满足 11 个不同场景的目标。
这些较早版本示例需要先在 Blender 4.x 试渲染，检查贴图、主体放置位置及相机是否碰墙。
默认位置仍为世界原点；在 catalog.scenes 中调整 position 后重新 plan。
本地环境访问 Blender 官方下载站返回 403，链接核实来自官方页面，下载需服务器或 Windows 实测。

也可给原有 Poly Haven 下载加上限，避免下载 GiB 包：

```bash
dgs-scenes --provider polyhaven --max-download-mib 300 --root "$DGS_ROOT" --insecure
```


Barcelona Pavilion 原包可能缺少 `.blend` 引用的 `water bump.jpg`，但包含 `water-raindrop.jpg`。
仅对 `pavillon_barcelone_v1.2.blend`，下载包内缺失的该贴图会替换为现有水波图，并打印 `[texture]`。
这是一项水面凹凸细节替代，不保证与原始图相同；其他场景不会套用这个名称替代。


### 外部场景灰白画面或主体 mask 全黑

外部文件可能选中了带全局材质覆盖的渲染层。管线会清除当前层的 material_override，保留实际材质。
如果世界原点不适合摆放，可显式增加 `dgs-render --auto-place`：在初始位置附近（XY 每步 4 单位、
最大正负 32 单位）找朝上的支撑表面，并检查全部指定轨迹帧中相机到主体中心及近似边缘的遮挡。
找到后打印 `[placement]`，实际坐标写入 render-report.json 的 subject_position。
找不到则报错，仍可手动指定 subject-position。该检查不保证整个主体体积无碰撞或语义上合适；
试渲染确认后，将实际坐标填入 catalog.scenes 的 position，再重新生成批量 plan。


### 所有素材组合的单帧检查

扫描后创建全部启用的 object/human × scene × background 组合；每个组合一张 720P 横屏远景。
外部场景自动寻找支撑和无遮挡位置，程序场景沿用设置。保留 RGB/mask/depth/报告，不编码视频，
不重复保存 scene.blend。第一帧检查不能保证所有景别、横竖屏和轨迹帧均正常。

```bash
dgs-dataset inventory --root "$DGS_ROOT"
dgs-dataset preview --catalog "$DGS_ROOT/catalog.json" --output "$DGS_ROOT/preview-plan.json" --render-root "$DGS_ROOT/renders/asset-previews" --samples 16
dgs-dataset run --plan "$DGS_ROOT/preview-plan.json" --blender "$DGS_BLENDER" --gpus 0,1,2,3 --retry-incomplete
```

inventory 的数量不足退出码 1 不影响 preview 读取已生成的 catalog；不要用 && 将两者连起来。
preview 打印实际图片数量（32 主体 × 14 场景 × 24 背景 = 10752 张）。
默认包括 12 个庭院变体；只检查下载场景，可给 preview 增加 `--external-scenes-only`。
run 重复执行会跳过完成项；失败详情在 preview-plan.run-report.json 和对应 logs 目录。

`renders/asset-previews/index.html` 是静态分页检查页，支持主体搜索、场景/背景筛选，每页 48 项，
RGB 图、mask 和报告链接。下载整个预览目录后可在 Windows 浏览器打开 index.html。
渲染过程中可刷新检查页查看新增结果，未生成与失败项显示“待生成或失败”，以批次报告为准。
