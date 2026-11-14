# 参考图追色、肤色保护和视频瘦脸：可行性研究

调研日期：2026-11-14。仅研究，未安装、下载模型或实测。以下耗时和工期均为工程估计，不是该机器的基准；代码许可不自动覆盖模型权重、数据及专利。

## 结论先行

**(a) 参考图追色 → LUT：能做。** 推荐 CPU 上按镜头采样非皮肤像素，拟合受约束的 Lab 均值/方差变换，采样成 33³ `.cube`，接现有 GRADE；约 **2–4 人日**。主要风险是参考图与视频场景构图不同导致统计失真，以及 LUT 无法表达局部语义。

**(b) 自动肤色保护：能做。** 推荐复用现有分割结果建立独立皮肤保护权重，在 GRADE 将全局 LUT 与保守的皮肤变换混合；约 **2–4 人日**。主要风险是蒙版边缘、遮挡与时间滞后，以及参考肤色不可靠时出现光晕或偏色。

**(c) 视频自动瘦脸：能做原型。** 推荐复用 478 点，按人跟踪并平滑，用局部反向采样 GLSL 做小幅下颌变形，同时对所有空间蒙版施加相同变换；约 **4–7 人日**。主要风险是脸缘背景弯曲、遮挡、侧脸及 GPU 余量；无法保证所有场景无背景抖动。

## 产品与公开信息

- [像素吐司 PixToast 官网](https://www.pixtoast.com/)列出的主体是深圳真视科技有限公司，定位 4K 人像美化、AI 追色的视频精修；[官方下载页](https://www.pixtoast.com/download)要求将链接发送至电脑，具体 Windows/macOS 支持及当前版本未从页面核实。它不是单纯的照片修图软件。
- [第三方体验视频及其页面转写](https://www.douyin.com/shipin/7612070633052325914)称导入一张照片给视频追色，提供面部重塑、瘦脸瘦身与身体肤色统一；同页另一体验者称大幅转身时可能扭曲。页面汇总多个视频，自动转写不等同官方规格。未找到可核实的独立「追色时保护肤色」开关、其精确行为或算法；身体肤色统一也不能证明追色有肤色保护。该页另一体验者称 299 元 600 豆、1080p 30fps 约 0.5 元/秒，仅是历史第三方报价，当前套餐、试用和收费条件未能从官方核实。
- [像素蛋糕](https://www.pixcakeai.com/)以照片修图为主；本次未核实其自身支持参考照片追色视频和视频自动瘦脸，不能把吐司功能归到蛋糕。第三方介绍 [Wink 桌面版](https://ai.fly63.com/wink)称参考图复刻色调、动态瘦脸；[Wink 官方](https://wink.cn/retouch-video)确认支持图片/视频的人脸美型，[官方身材美型页](https://wink.cn/ai-body-editor)称能区分人物且背景不扭曲。桌面 Wink 与 WinkStudio 的具体版本、参考图入口和当前权益仍需实机确认。[醒图](https://www.capcut.cn/activities/xingtu)以照片编辑为主，本次未核实其视频两项能力。
- 商业产品的分割、配准、补背景和时序算法未公开到足以确认；宣传「背景不扭曲」是厂商效果主张，不是其实现原理或所有场景的保证。

## 开源追色路线

约定：速度指缩略图统计/推理加一次 LUT 生成，不是整段视频渲染；下表「未测」表示没有可靠的 GTX 1060 / Xeon 实测。传统方法无需模型权重，33³ RGB float32 LUT 约 0.41 MiB。代码许可状态单独列于许可表。

| 路线及代码 | 输入、LUT 与质量 | 模型大小与预计一次生成速度 |
|---|---|---|
| [Reinhard 实现](https://github.com/jrosebr1/color_transfer) | 两张图的 Lab 均值/标准差；拟合后对 RGB 规则网格执行变换，写 `.cube`。自然、快速，但只匹配一阶统计，场景差异会误导；无语义肤色保护。注意 OpenCV Lab 的编码范围和 RGB 顺序。 | 无模型；CPU 缩略图加 33³ 采样预计约 0.05–1 秒，未测。 |
| [MKL/Monge–Kantorovich 线性实现](https://github.com/frcs/colour-transfer/blob/master/colour_transfer_MKL.m) | 两张图拟合均值与完整协方差，形成颜色空间仿射映射，采样为 LUT；能匹配通道相关性，但分布多峰或场景不对应时仍易偏色，需正则化小特征值；肤色须另保护。 | 无模型；CPU 预计 0.1–2 秒，未测。仓库代码许可未核实，不建议直接复制。 |
| [scikit-image 直方图匹配](https://scikit-image.org/docs/stable/api/skimage.exposure.html#skimage.exposure.match_histograms) | 通道 CDF 可用 1D 曲线后采样到 3D LUT；保留分布形态但逐通道可能扭曲色相，对构图比例敏感；没有皮肤语义。 | 无模型；CPU 预计 0.1–2 秒，未测。 |
| 区域对应：[局部颜色迁移原始论文](https://www.cs.tau.ac.il/~turkel/imagepapers/ColorTransfer.pdf)；[ColorTransferLib](https://github.com/hpotechius/ColorTransferLib) 汇集多种方法 | 匹配天空、皮肤等对应区域可减小构图偏差，但参考图也须分割，误对应会产生接缝；不同位置相同 RGB 要不同结果时**无法**编码为单一 3D LUT。可分别拟合背景与肤色 LUT 再按蒙版混合。库和各子算法许可未核实，不建议直接集成。 | 无固定模型大小；依区域与分割器而异，CPU 数秒以上亦可能，未测。 |
| [Image-Adaptive-3DLUT](https://github.com/HuiZeng/Image-Adaptive-3DLUT) | 输入源图、融合基础 LUT；是图像增强，不是任意参考图追色；需另训练参考图条件分支。空间一致，但不自动保护肤色。 | 权重大小未核实；Pascal 预计每次数十毫秒至数秒，含运行时初始化可能更长，未测。 |
| [AdaInt](https://github.com/ImCharlesY/AdaInt) | 输入源图的自适应非均匀 LUT，非参考图追色；需重新训练，且要在规则 RGB 网格重采样以适配现有 GRADE，可能损失精度。肤色另保护。 | 权重大小未核实；预计数十毫秒至数秒，未测；PyTorch/CUDA 扩展与旧驱动、Python 3.12 的兼容性须验证。 |
| [SepLUT](https://github.com/ImCharlesY/SepLUT) | 源图自适应 1D+3D 级联，非参考图条件；固定参数后可将整个复合映射重采样为单个 3D LUT，可能损失精度；未提供肤色语义保证。 | 权重与许可未核实；预计数十毫秒至数秒，未测；不作为商用依赖。 |
| [Neural Preset](https://github.com/ZHKKKe/NeuralPreset)，[论文](https://openaccess.thecvf.com/content/CVPR2023/papers/Ke_Neural_Preset_for_Color_Style_Transfer_CVPR_2023_paper.pdf) | 2023，源图和参考图提取颜色映射；固定条件后 DNCM 是逐色映射，可采样成 LUT，输出有近似误差；无肤色保护保证。官方仓库非商用，视频 demo 标 TBD。 | 论文对比报告 5.15M 参数；一次生成速度在 1060 上未知，无法套用论文 4K 推理速度。 |
| [Deep Preset 论文](https://arxiv.org/abs/2007.10701) | 参考图驱动色彩预设，理论上固定全局逐色操作可采样；未核实可用官方代码、权重与许可，不作商用选择；局部操作不能无损烘焙。 | [D-LUT 对比](https://openaccess.thecvf.com/content/WACV2025/papers/Li_D-LUT_Photorealistic_Style_Transfer_via_Diffusion_Process_WACV_2025_paper.pdf)报告 267.77M 参数；GTX 1060 用时和显存未知。 |
| [D-LUT 论文及所列代码](https://github.com/leemojjang/D-LUT) | 2025，参考图生成可导出 3D LUT；随机扩散过程要固定随机种子并每镜头缓存。论文所列仓库本次访问返回 404，无法核实代码、许可、权重或肤色保护，不能当作可用开源依赖。 | 论文称无需预训练；实际生成耗时、显存和 1060 支持均未核实。 |
| [SA-LUT](https://github.com/Ry3nG/SA-LUT)，[论文](https://arxiv.org/abs/2506.13465) | 2025 参考图驱动、空间自适应 4D LUT；可处理局部差异，但空间维使其一般不能无损压成单一 3D LUT；肤色无专门保证。仓库许可内容及权重条款未核实。 | 参数、权重及 1060 速度未核实；不能直接放进现有 GRADE。 |

## 肤色保护设计

1. 每个镜头从若干代表帧采样，排除源图皮肤、过曝、极暗、低置信度像素；参考图也尽量排除皮肤，避免参考人脸面积支配背景统计。无可靠参考蒙版时明确退化为整体统计或提示用户选图。若样本太少、方差接近零则回退单位 LUT；裁剪变换幅度及高光，镜头内固定，镜头切换重算或对 LUT 短暂交叉淡入。统一在 GRADE 的 SDR RGB 色域和传递函数下拟合，HDR 先经现有归一化。
2. 单独拟合皮肤变换：默认身份映射或只允许小幅亮度、色度偏移；若参考图可靠地检测到肤色，可用稳健中位数目标，但限制 ΔL、色相、饱和度，保留原有肤色差异，不强推统一白肤。用户选择保护强度；不假设所有肤色同色相。
3. 着色器中 `mix(global_lut(rgb), skin_lut(rgb), clamp(mask * protection, 0, 1))`，全局强度在两路一致处理；零保护时退化为原调色。固定 LUT 只稳定映射，源视频变化、蒙版本身仍会闪烁。
4. 现有 `face.py` 的 R/G 通道是磨皮/提亮权重，含身体降权及眼唇挖空，**不是通用完整皮肤概率**。应新增独立保护通道或原始分割置信度，避免复用磨皮权重导致脖子漏保护。现有每两帧分割插值、EMA 和切镜重置可复用；对边缘做轻微羽化与置信度回退，检查快速运动拖影。嘴唇、化妆和头发分别决定是否保护。参考 [MediaPipe 图像分割](https://ai.google.dev/edge/mediapipe/solutions/vision/image_segmenter) 和 [颜色迁移论文](https://www.cs.tau.ac.il/~turkel/imagepapers/ColorTransfer.pdf)，以上具体融合是本项目建议，非声称论文已实现。

## 瘦脸路线与视频问题

- [GPUPixel](https://github.com/pixpark/gpupixel) 是 Apache-2.0 的实时滤镜，提供[瘦脸和大眼接口](https://gpupixel.pixpark.net/call/beauty_effects)；适合研究局部变形，直接移植仍须核对 detector、第三方库和模型许可及 landmark 索引。另有 [face-beautifier](https://github.com/ctbot000/face-beautifier)（MIT，MediaPipe + WebGL，含下颌调整），可参考映射与 shader，不能假定 WebGL 能直接用于 OpenGL 3.3。
- [MLS 图像形变](https://github.com/Jarvis73/Moving-Least-Squares)可用控制点作平滑变形；该仓库许可未核实。TPS 或 478 点三角网格可表达更复杂局部形状，但需要边界固定、避免三角翻转与遮挡问题；用 CPU 全分辨率计算不适合本项目。首版选少量下颌控制点、局部反向采样，GPU 耗时预计增加约 0.5–3 ms/1080p，**未测且与 DirectML 争用**，必须以完整流水线测 fps。
- 根据脸宽设置作用半径和最大位移，画面每个输出像素反向查询源坐标；限制权重在脸部周边平滑衰减。按真实时间戳对每个人的关键点使用 [One Euro 滤波](https://github.com/casiez/OneEuroFilter/blob/main/python/OneEuroFilter/OneEuroFilter.py)，低速抑抖、高速减滞后；切镜、丢脸及时间跳变重置，检测丢失时逐步淡出而非跳变。
- 背景直线风险：缩小影响区域、轮廓外设固定锚点、用人体/脸轮廓约束及渐变；但单纯将位移裁到皮肤内不能改变外轮廓，还可能产生裂缝。要真正收缩轮廓需处理新露出的背景，复杂情况下须背景重建或多帧补洞，遮挡处无法保证真实。不要声称商业软件一定使用这些方法。
- 大转头时按姿态、可见度、点几何合理性降低强度或退出；手、头发、眼镜等遮挡需额外保护。`face.py` 当前设置最多 4 张脸，但需稳定身份关联、每人独立滤波，处理交叉、遮挡和重叠作用区；先只支持最大脸，明确多脸未完成。

## 管线落地与验收

- `face.py` 当前分析数据包括分割与由 landmarks 构造的图层；要增加每人原始关键点、时间戳、稳定 ID/有效状态及独立皮肤权重，确认工作进程传输和坐标方向。现有 `gpu.py` 的 `MASKBUILD` 组装并平滑蒙版，HEAL/RETOUCH 后 GRADE。
- 建议顺序：解码/YUV2RGB → 原图分析与 MASKBUILD → **WARP RGB 和同坐标 WARP 所有 mask/layers** → HEAL → RETOUCH → 双路径 GRADE → bloom/FINISH/TOYUV。瘦脸应先于 HEAL，修复和磨皮才与变形后的脸对齐；HEAL 的眼下、斑点层、皮肤分割都要同样变形，避免用变形后 RGB 配原位置蒙版。注意 ping-pong 避免读写同一纹理。若保留原 landmark 做后续几何计算，也需同步映射到输出坐标。
- 先做三项独立原型：① 固定单镜头的非肤 Lab → 33³ cube，提供强度与单位 LUT 回退；② GRADE 双 LUT 加保护权重，可视化蒙版及颈部；③ 单脸小幅下颌 warp，同步 warp 蒙版，失跟淡出。工期为开发估算，不含模型训练、完整 UI 和复杂背景补洞；合并与回归另预留 2–4 人日。
- 验收用项目现有竖屏、双人、霓虹、户外素材及新增转头、遮挡、直线背景和肤色范围样片；检查色卡、LUT 三线性插值与 `.cube` 顺序、镜头切换、运动边缘、脸/颈衔接、面部身份切换。比较无功能、单功能、全部开启的整段导出 fps、GPU 时间、显存和闪烁；当前 GPU 已是瓶颈，0.5–3 ms 估计不能保证 30 fps。

## 推荐项目许可表

| 项目 | URL | 许可 | 商用闭源集成 |
|---|---|---|---|
| color_transfer | https://github.com/jrosebr1/color_transfer | MIT | 可以，保留版权与许可声明 |
| scikit-image | https://github.com/scikit-image/scikit-image | BSD-3-Clause | 可以，遵守声明条件 |
| GPUPixel | https://github.com/pixpark/gpupixel | Apache-2.0 | 代码可以，保留声明；另查模型和第三方组件 |
| face-beautifier | https://github.com/ctbot000/face-beautifier | MIT | 代码可以；另查模型与依赖 |
| OneEuroFilter Python | https://github.com/casiez/OneEuroFilter/blob/main/python/OneEuroFilter/OneEuroFilter.py | BSD-3-Clause | 可以，保留声明 |

调研用途而非首版依赖：Image-Adaptive-3DLUT、AdaInt 代码为 Apache-2.0，但权重和数据须另核查；Neural Preset 官方仓库为 CC BY-NC-SA 4.0，不能直接商用。未核实许可的项目不能因公开源码就视作可商用。
