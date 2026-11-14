# 像素蛋糕视频版 · M0 命令行原型

面向抖音 / 视频号竖屏短视频的 GPU 风格化调色。

## 安装
```bash
python -m pip install numpy moderngl Pillow
python -m cake build-luts
```
依赖：PATH 里有 ffmpeg/ffprobe（含 zimg）；显卡支持 OpenGL 3.3。

### 模型（精修用，不在仓库里）
```bash
python -m pip install mediapipe onnxruntime-directml opencv-python
```
下载到 `models/`（Apache 2.0）：
- `selfie_multiclass_256x256.tflite`：https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite
- `face_landmarker.task`：https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
- GPU 分割模型 `selfie_multiclass_256x256.onnx` 由上面的 tflite 转换得到：先建转换环境 `python -m venv .cv`，在里面安装 `tensorflow-cpu tf2onnx`，再运行 `python tools/convert_seg_onnx.py`。没有 onnx 文件时会自动改用 MediaPipe 的 CPU 分割（速度较慢）。

## 用法
```bash
python -m cake styles                                   # 列出风格
python -m cake still 视频.mp4 --t 2.5                    # 截一帧：原片 + 全部风格对比图
python -m cake grade 视频.mp4 -s film_warm               # 整段调色 -> 视频_film_warm.mp4
python -m cake grade 视频.mp4 -s ccd --strength 0.7      # 强度 0~1.5
python -m cake grade 视频.mp4 -s 我的.cube               # 直接套任意第三方 .cube LUT
python tools/platform_sim.py 成片.mp4 --orig 原片.mp4    # 模拟平台二次压缩，看颗粒还剩多少
python tools/make_chart.py chart.mp4                    # 生成色卡测试视频
```

## 桌面界面（M2）
```bash
python -m pip install PySide6-Essentials
python -m cake ui                      # 也可以带上视频：python -m cake ui a.mp4 b.mp4
```
- **左：视频队列**。支持添加视频、添加文件夹，也可以直接把文件拖进窗口；导出后会标上 ✓ 或 ✗。
- **中：预览**。原片和效果左右对比，分割线可以拖动，也可以切换成只看效果或只看原片；支持播放、暂停、拖动进度条。
  - 预览按短边 720 渲染，精修全开也能按原帧率播放（实测横屏 25.2 fps、竖屏 24.1～24.4 fps）。
- **右：参数**。风格、强度、磨皮美颜、祛痘淡斑、黑眼圈、保留痣、标出检测结果。
  - 暂停时调节参数，当前帧会立刻重新渲染（强度约 0.1 秒；风格的 LUT 在启动时已在后台预加载）。
  - 祛痘和黑眼圈默认跟随磨皮强度一起变化，手动拖过之后就各自独立。
- **导出**：可以导出当前视频或全部导出，带进度条，可以取消（会删除写了一半的文件）。导出时自动暂停预览，避免抢占 CPU。导出完成后可以一键打开输出文件夹。
- **每段视频单独记参数**：选中哪段，面板就显示那段自己的参数，导出时也按各自的参数处理。点「应用到全部」可以把当前参数复制给整个队列。新加入的视频默认沿用当前参数。
- **我的预设**：「存为预设」可以把当前的风格、强度和精修参数保存起来，下次选中后点「应用」即可。预设保存在 `%APPDATA%\cake\presets.json`。
- **快捷键**：

  | 按键 | 作用 |
  |---|---|
  | 空格 | 播放 / 暂停 |
  | ← → | 逐帧后退 / 前进（暂停时） |
  | 按住 `\` | 临时看原片，松开恢复 |
  | ↑ ↓ | 切换队列里的上一段 / 下一段 |
  | Ctrl+O | 添加视频 |
  | Ctrl+E / Ctrl+Shift+E | 导出当前 / 全部导出 |
- **队列缩略图**：后台抽取每段视频第 1 秒的画面作为图标。
- **精修模型在启动时就后台加载**，选好视频时通常已经就绪。
- **自动测试**：`python tools/test_ui.py`（离屏运行，不弹窗口），覆盖加载、调参重新渲染、跳转、切换视频、导出后取消。
  - 截图：`python -m cake ui 视频.mp4 --t 3 --screenshot shot.png`（设置环境变量 `QT_QPA_PLATFORM=offscreen` 后不弹窗口）。

## 人像精修（M1 第一步）
```bash
python -m cake grade 视频.mp4 -s film_warm --retouch 0.5     # 调色 + 精修（默认 0.5）
python -m cake grade 视频.mp4 -s none --retouch 0.5          # 只精修不调色
python -m cake grade 视频.mp4 -s ccd --retouch 0             # 关闭精修（快 3～5 倍）
python -m cake face 视频.mp4 --t 3 [-s film_warm]            # 精修检查图：0/0.5/1 全图 + 脸部放大
python tools/flicker.py 原片.mp4 成片.mp4                     # 测量处理带来的闪烁（Codex 编写）
```
- **皮肤蒙版**：用 MediaPipe 多类别人像分割，分出脸部皮肤和身体皮肤；再用人脸关键点（478 点）把眼睛、眉毛、嘴唇挖掉，避免这些部位被磨糊。
- **磨皮**：GPU 上做频率分离。先用保边的双边滤波去掉中频的斑点和不均匀，再把原图约 1px 的毛孔细节加回去，避免"塑料脸"。磨皮半径按人脸大小自动调整。
- **肤色**：在皮肤蒙版内提亮中间调、略微偏粉。原来写在 LUT 里、按颜色判断的提亮已关闭，所以沙子、木头不会再被误提亮。
- **祛痘、淡斑**（`--spots`，默认跟随 `--retouch`；`--remove-moles` 连痣一起去掉，默认保留痣）
  - 先在半分辨率下、只取皮肤像素算两层模糊（约痘大小、约 3 倍痘大小），比较两者的差，找出比周围皮肤更暗或更红、尺寸接近痘的区域。
  - 再过 4 道检查：Hessian 形状检测（必须是圆斑，排除线和边缘）；像素本身要比周围暗或红（排除边缘的亮侧）；8 点环形检测（四周至少 7 个方向是更亮的皮肤，排除法令纹、鼻翼、轮廓边缘）；周围区域本身也要主要是皮肤。
  - 修补时用周围皮肤的低频颜色，再从邻近位置借约 1px 的毛孔纹理（限制幅度，避免带进边缘产生重影）。
  - 鼻孔和内眼角被单独挖掉，不参与检测。
  - 用 `python -m cake face 视频.mp4 --debug` 查看检测结果：红色是痘或斑，蓝色是黑眼圈区域。
- **黑眼圈**（`--eyes`）：根据人脸关键点，在下眼睑往下约 0.07～0.42 个眼宽的范围画一条柔和的带状区域。只把这块的低频亮度和颜色向正下方脸颊靠拢（只提亮、不压暗），高频纹理不动，所以不会抹掉卧蚕和细纹理。
  - 实测加上祛痘和黑眼圈后，脸部额外闪烁的峰值从 0.54 级升到 0.62 级（只磨皮时 0.54），几乎没有增加。
- **防闪烁**：分割每 2 帧跑一次，中间帧用前后两次结果插值；关键点每帧都跑；蒙版之间做指数平滑，遇到镜头切换时重置。
  - 实测精修 0.5 时，脸部额外闪烁的峰值为 0.9 级（8bit），1.0 时为 1.8 级，都在肉眼不易察觉的范围内。
- **速度：已达到实时**（GTX 1060 + E5-2666 v3）。表中数字为持续处理速度，精修强度 0.5，含编码：

  | 素材 | 源帧率 | 速度 |
  |---|---|---|
  | 1080×1920 竖屏（霓虹、街头、海滩） | 23.976 | 26～28 fps |
  | 720p 横屏（户外、室内、双人） | 25 | 40～51 fps |
  | 关闭精修 | | 34～98 fps |

  实现方式：
  - **分割**：在 GPU 上跑（ONNX + DirectML，单帧 22ms，MediaPipe CPU 版要 145ms），每 2 帧跑一次，中间帧在 GPU 上插值。
  - **关键点**：每帧都跑，使用 VIDEO 跟踪模式。
  - **分析在独立进程中进行**：用线程时各线程会抢 Python 的 GIL，主循环大部分时间都在等锁。
  - **主线程只上传纹理**：蒙版合成和时间平滑都在 GPU 上完成，主线程每帧开销从约 32ms 降到 0.9ms。
  - **GPU 直接输出 NV12**：不再经过 ffmpeg 的 swscale，管道传输量减半。
  - **编码**：使用 Windows Media Foundation 硬件编码（`h264_mf`，在 NVIDIA 显卡上实际调用驱动里的 NVENC），High profile 16Mbps，画质 PSNR 高于 x264 CRF17。
- **2026-11-14 效率实测**（`tools/bench_matrix.py`）：精修全开时，竖屏 1080p 导出约 28～33 fps，横屏 720p 约 35～40 fps；关掉精修分别为 72 fps 和 128 fps。CPU 平均占用只有约 32%。分析进程加到 4 个反而更慢，分割改回 CPU 则速度减半，所以**当前瓶颈是 GPU**：分割用的 DirectML 和渲染用的 OpenGL 在同一块 GTX 1060 上互相争抢。主线程的 GPU 读回已改为双缓冲异步读回，渲染耗时从 11.8ms 降到约 4ms。YUV 直通解码因为会给 GPU 加活，实测没有收益，默认关闭（`CAKE_YUV=1` 可打开）。
- **启动**：分析进程首次加载模型约 3 秒，已和渲染、编码的初始化重叠进行。批量处理（`grade 文件夹` 或多个文件）共用同一组分析进程，只在开头等一次。
- **分割后端**：环境变量 `CAKE_SEG=cpu` 可切回 MediaPipe 的 CPU 分割；`CAKE_ANALYZER=thread` 可切回线程模式（用于对比）。
  - GPU 模型由 `tools/convert_seg_onnx.py` 转换（需要 `.cv` 转换环境，约 1.6GB，只在重新转换时用到，可以删掉）。
  - 与 MediaPipe 的一致性由 `tools/test_seg_gpu.py` 检查：正常光线下全部通过；紫红霓虹画面因缩放插值方式不同，软 IoU 为 0.85～0.92（测试脚本会如实报失败）。精修效果和闪烁实测与 CPU 版相当。
- **模型**放在 `models/`（Apache 2.0）：`selfie_multiclass_256x256.tflite`、`face_landmarker.task`。

## 管线
```
ffmpeg 解码 ─► 色彩空间归一 ─► GPU: 3D LUT ─► 高光溢出/柔光 ─► 色散/柔化/暗角/颗粒/日期水印/抖动 ─► ffmpeg 编码
  (强制CFR, 旋转矫正)  (HLG/PQ→SDR mobius, BT.2020→709, 10bit走16bit管线)                          (GPU 转 NV12，硬件编码 MF/NVENC)
```

| 文件 | 作用 |
|---|---|
| `cake/probe.py` | ffprobe：HDR、位深、旋转、VFR 帧率归整、音频 |
| `cake/media.py` | 解码到原始 RGB / 原始 RGB 编码；编码器自动检测 |
| `cake/gpu.py` + `cake/shaders.py` | moderngl 渲染：调色 → 亮部提取 → 模糊 → 合成 |
| `cake/looks.py` | 用代码生成 LUT 的色彩数学（含肤色保护） |
| `cake/styles.py` + `styles/*.json` | 风格预设 = LUT + 质感参数 |
| `tools/platform_sim.py` | 平台压缩模拟（Codex 编写） |

## 内置风格
- `film_warm` 胶片暖调：Portra 风格，暖色只加在环境和高光上，皮肤单独提亮、保持粉嫩
- `teal_orange` 青橙电影·风景城市：暗部偏青、高光偏橙，适合风景、城市、旅拍
- `teal_orange_portrait` 青橙电影·人像：同一 LUT 只用 55% 强度，几乎无暗角、无颗粒
- `ccd` CCD 复古：明亮偏冷，带光晕、柔化、色散、彩色噪点、橙色日期水印（默认取文件修改日期，放在抖音安全区右下角）

### 抖音适配规则（所有风格都遵守）
- 高光不压灰：高光肩部曲线保证纯白仍输出接近纯白
- 整体亮度不低于原片；暗角轻（四角最多比原来暗约 0.05）
- 肤色：色相拉向约 17°（白里透红），中间调提亮约 4 个点，饱和度略降
- 文字和水印放在 1080×1920 画面的安全区内（约 x 60～900、y 190～1480），避开右侧按钮栏和底部文案区
- 用 `python tools/eval_looks.py 视频.mp4` 可量化检查以上指标

## 已知问题（M0）
- **NVENC（ffmpeg 原生）不可用**：ffmpeg 8.1 的 NVENC 要求驱动 610 以上，本机是 526.47，而 GTX 1060 最高只支持 580 系列驱动。现在通过 Media Foundation 调用硬件编码（自动选择，顺序为 NVENC > MF > x264），不再需要 x264。
- **HDR 素材较慢**（约 11fps）：色调映射在 CPU 上用 zscale 计算。M1 计划把 HLG/PQ 转换挪到着色器里。
- **颗粒难以保留**：海滩实拍素材按 3Mbps / 1.5Mbps 模拟压缩后，颗粒分别剩约 34% / 24%；色卡上只剩 17% / 3%。M1 要做"抗压缩颗粒"调参。
- **LUT 里的肤色色相保护仍然只看颜色**：红色霓虹灯下仍会把人脸往自然肤色拉。下一步改为由皮肤蒙版驱动。
- **精修还没做**液化（瘦脸、大眼）、牙齿美白、法令纹淡化。
- **祛痘检测比较保守**：以"不误伤五官和轮廓"为优先，所以成片的雀斑、很淡的斑基本保留，主要去掉孤立的痘和小斑点。
- **黑眼圈的脸颊参考点固定取画面正下方**：头部明显歪斜时，参考位置会偏。
- 速度瓶颈现在主要在 1080×1920 竖屏的分析进程上（余量约 10%）。如果要在 30fps 竖屏素材上实时处理，下一步可以把关键点检测也挪到 GPU 上。
- **还缺 iPhone HDR 实拍素材**。

## 测试样片 · 亚洲人像
同样来自 Mixkit：`asian_hush_48036`（户外近景）、`asian_indoor_48688`（室内正脸）、`asian_mother_child_48689`（双人，含儿童），这三段均为 1280×720；另有 `asian_closeup_v_101040`、`asian_thought_v_101042`（竖屏霓虹，脸部大多被遮挡，只用来测试稳定性）。

## 测试样片 `samples/`
来自 Mixkit（Mixkit Free License，可免费商用），仅用于开发测试：
`beach_daylight_1221`、`street_mixed_1227`、`neon_night_1230`、`garden_child_48601`（均为 1080×1920，23.976fps）。
`samples/compare/` 是各风格的对比图，`samples/out/` 是导出的成片。
