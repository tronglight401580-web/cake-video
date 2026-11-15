# 开源同类项目调研与复用建议

调研日期：2026-11-14。项目链接同时是功能及许可证的来源；星数会变化，unverified 表示本次未确认，不能按零理解；最后提交/版本日期无法确认时同样标记 unverified。商业可用性仅为初筛，分发时须复核选定版本、依赖、模型权重和数据集的许可。GPL 可商用，但分发组合程序可能有源码等义务；MIT/Apache 可商用，须遵守声明等条件。所有 Windows 速度均未在本项目硬件实测；论文与项目自报速度不能当作本产品 FPS。

本地实际代码优先于文档：`cake/render/passes/warp.py` 已注册 250，GPU 构建位移场、模糊、时域处理并重映射 RGB 与蒙版；`docs/ARCHITECTURE.md` 仍写预留，已过时。任务给出的约 400 ms CPU/帧是待复现的报告，不推定瓶颈位置。下表集成成本为相对估计：低=数天以内，中=数天至数周，高=数周以上，均不含商用许可及完整验证。

## 整体产品与视频工具

| 项目、链接、许可、星数、最新提交/发布 | 成熟度、平台与能力、质量证据、接入成本及结论 |
|---|---|
| [GPUPixel](https://github.com/pixpark/gpupixel)：Apache-2.0，允许商用；约 2.5k stars；日期 unverified。依赖及检测器另审。 | C++/OpenGL，跨平台含 Windows；GPU 实时滤镜，瘦脸、大眼及磨皮，仓库有 demo；其 [桌面代码](https://github.com/pixpark/gpupixel/blob/main/demo/desktop/app.cc) 显示相关控件及 landmarks 输入。中至高：C++ 包装、GL 上下文及 landmark 适配；优先借鉴形变，磨皮仅 A/B。 |
| [face-beautifier](https://github.com/ctbot000/face-beautifier)：MIT，商用可；stars、日期 unverified。 | 小型浏览器/MediaPipe/WebGL 项目，GPU 磨皮、瘦脸及化妆，有在线 demo 和几何测试；Windows 浏览器可用，原生 Python 未验证。中：移植 GLSL 和坐标约定；借鉴局部控制及测试。 |
| [Beauty-Camera-AI](https://github.com/galaxeeranger/Beauty-Camera-AI)：许可、stars、日期 unverified，未经授权勿复制。 | Python/OpenCV/MediaPipe 摄像头样例；Windows 可尝试，瘦脸效果、GPU 和帧率未确认。低至中；作为实现思路与基准，非生产替换。 |
| [FaceGlow](https://github.com/wangyifan349/FaceGlow)：许可、stars、日期 unverified；InsightFace 权重通常非商用。 | Python/OpenCV/InsightFace，仓库展示磨皮与面颊/下颌瘦脸；仅照片批处理，非实时视频。中；借鉴保护五官思路，不直接接入。 |
| [OBS](https://github.com/obsproject/obs-studio)：GPL-2.0，商用须遵守 GPL；stars、日期 unverified。 | C/C++、Windows、成熟实时 GPU 直播；[内置 LUT 滤镜](https://obsproject.com/kb/filters-guide) 可作效果基准。整合 OBS 高成本；借鉴交互，不替换。 |
| [obs-beauty-filter](https://github.com/wuxiwuhen/obs-beauty-filter)：许可、stars、日期 unverified。 | Lua + OBS shader，GPU 肤色检测/磨皮/美白，有演示；不等于 landmark 精修。中：需移植 effect shader，许可未明先只观察效果。 |
| [Olive](https://github.com/olive-editor/olive)：GPL-3.0；stars、日期 unverified。 | 跨平台 C++ 非线编，支持颜色处理，GPU 路径与速度随版本而异；开发版本成熟度须确认。高；调色及 UI 对照，不嵌入。 |
| [Shotcut](https://github.com/mltframework/shotcut)：GPL-3.0；约 15.7k stars；日期 unverified。 | Windows Qt/MLT 成熟编辑器，颜色分级及 LUT；GPU 实时效果取决滤镜及机器。高；对比滤镜/工作流，不直接复制 GPL 代码。 |
| [Kdenlive](https://github.com/KDE/kdenlive)：GPL-3.0；stars、日期 unverified。 | Windows/Linux，成熟 MLT 视频编辑器；色彩效果和时间线可参考，具体加速路径未验证。高；工作流对照。 |
| [FFmpeg](https://github.com/FFmpeg/FFmpeg)：LGPL-2.1-or-later 为主，构建选项可能变 GPL；stars、日期 unverified。 | 跨平台 C，成熟；[lut3d/haldclut](https://ffmpeg.org/ffmpeg-filters.html#lut3d) 是 LUT 应用而非生成。通常 CPU 路径，硬编不意味着滤镜 GPU；低：CLI 基准/离线导出，保留 GL 实时链。 |
| [OpenColorIO](https://github.com/AcademySoftwareFoundation/OpenColorIO)：BSD-3-Clause；stars、日期 unverified。 | C++/Python，成熟电影工业色彩管理，GPU shader 和 LUT 处理；质量证据为官方配置与规范，不自动生成审美风格。中：引入色彩空间/显示管理，核对配置文件授权。 |
| [VapourSynth](https://github.com/vapoursynth/vapoursynth)：LGPL-2.1；stars、日期 unverified；插件各有许可。 | Windows/C++ 核心、Python 脚本，离线逐帧处理；[vs-denoise](https://github.com/Jaded-Encoding-Thaumaturgy/vs-denoise) 提供去噪组合，许可、stars、日期 unverified。可借鉴遮罩与时域滤波，插件可能依赖 GPU 或 CPU；缺少面部语义，集成高，不替换实时精修。 |
| [AviSynth+](https://github.com/AviSynth/AviSynthPlus)：GPL-2.0；stars、日期 unverified；插件单独审查。 | Windows 脚本视频处理成熟生态；如 [TemporalDegrain2](https://github.com/Asd-g/AviSynthPlus-Scripts) 脚本，许可、stars、日期 unverified，去噪不是祛痘。CPU/GPU 取决依赖；高成本，离线对照。 |

## 按模块的候选

| 项目、许可、stars、最后提交/版本 | 平台、性能、质量与复用 |
|---|---|
| [Colour](https://github.com/colour-science/colour)：BSD-3-Clause；stars、日期 unverified。 | 成熟 Python 色彩科学/变换和 LUT，CPU 计算 LUT 后可上传 GL；有文档和数值测试。低至中；借鉴色域、传递函数及数值校验，非现成电影预设。 |
| [Reinhard color_transfer](https://github.com/jrosebr1/color_transfer)：许可、stars、日期 unverified。 | Python/OpenCV，Lab 均值方差统计；论文与样例可对照，CPU 可一次生成映射，难处理内容分布不匹配。低；参考公式和对照，许可未明确前不复制。 |
| [MKL colour transfer](https://github.com/mahmoudnafifi/colour_transfer_MKL)：许可、stars、日期 unverified。 | Python 协方差匹配；有算法说明和示例，CPU 一次计算，非视频时序算法。低；与现有参考色及直方图匹配做离线对照，防协方差退化。 |
| [Neural Preset](https://github.com/ZHKKKe/NeuralPreset)：许可、权重许可、stars、日期 unverified。 | PyTorch 研究原型；[CVPR 2023 论文](https://openaccess.thecvf.com/content/CVPR2023/papers/Ke_Neural_Preset_for_Color_Style_Transfer_CVPR_2023_paper.pdf) 报告 4K 实时色彩迁移，非本机 Windows DirectML 测量。高：模型导出/权利/跨帧稳定与肤色保护；研究比较，勿直接上生产。 |
| [Deep Preset](https://github.com/minhmanho/deep_preset)：许可、权重许可、stars、日期 unverified。 | WACV 2021 学术照片色彩迁移，论文和代码；Windows GPU/实时及权重可用性未确认。高；参考编辑参数预测思路。 |
| [ABPN 论文](https://openaccess.thecvf.com/content/CVPR2022/papers/Lei_ABPN_Adaptive_Blend_Pyramid_Network_for_Real-Time_Local_Retouching_of_CVPR_2022_paper.pdf)：代码、权重、许可、stars、发布日期 unverified（论文 2022）。 | 照片局部修饰的金字塔网络，论文有质量及性能结果；不等于可直接获得商用可用权重，Windows GPU、视频稳定性未知。高；研究与离线基准，不替换。RetouchFormer 的适用官方仓库与授权本次未可靠确认，暂不列为可复用项目。 |
| [face-parsing.PyTorch](https://github.com/zllrunning/face-parsing.PyTorch)：代码 MIT；权重/训练数据许可 unverified；stars、日期 unverified。 | BiSeNet 人脸语义分割，PyTorch/样例图；导出 ONNX 后可试 DirectML，Windows GPU 速度未实测。中：裁剪、坐标反变换、时序和平滑；眼唇等细分类可补充现有 selfie 分割。 |
| [InsightFace](https://github.com/deepinsight/insightface)：代码 MIT，官方预训练模型明确仅非商用研究，商用需授权；stars、日期 unverified。 | Python/C++、ONNX 人脸检测和 landmarks；模型多、质量例子丰富，但检测不等于皮肤 parsing。DirectML 兼容与实际速度待测；中高，模型许可未解决不替换 MediaPipe。 |
| [Blind Video Temporal Consistency](https://perso.liris.cnrs.fr/nbonneel/consistency/)：论文/代码许可、stars、日期 unverified。 | 研究级视频一致性；有论文和对照示例，离线处理及光流方案适合参考，不证明 Windows 实时。高；用于闪烁对照而非逐帧直接接入。 |
| [Learning Blind Video Temporal Consistency](https://arxiv.org/abs/1808.00449)：论文 2018；代码、权重许可、stars、日期 unverified。 | 论文提出循环网络，报告实时实验；硬件与本项目不同，Windows GPU/ONNX 待验。高；参考运动补偿、遮挡和场景切换。 |

其他算法：MLS 的控制点变形可用于更平滑全局形状，但求解、边界线及多脸遮挡成本较高；优先使用局部径向核。直方图匹配能增强分布拟合，但对画面内容和极端曝光敏感，宜只在镜头级采样、肤色分区并限制强度。以上为方法而非已确认可商用的实现。

## 商业参考（功能定位，不代表开源或可借用代码）

| 产品 | 公开定位及证据 |
|---|---|
| 像素蛋糕 PixelCake | [官网](https://www.pixcakeai.com/) 以影像修饰为核心；其当前视频版的具体追色、精修功能和可用范围本次 unverified，不以照片功能推定视频功能。 |
| 美图 Wink | [Wink 官网](https://wink.ai/) 面向视频修饰、美颜及画质增强；具体地区/版本的塑形和调色功能需实机确认。 |
| 剪映 / CapCut | [CapCut 官方视频美颜](https://www.capcut.com/tools/video-beauty-filter) 提供视频美颜效果，色彩及脸型功能依版本和地区变化；建议分别用实际版本对照。 |
| 醒图 | [醒图官网](https://www.xingtu.cn/) 以图像编辑为主；其视频精修/塑形/调色能力本次未确认，不把图片工具当作视频功能。 |
| FaceUnity | [开发者中心](https://www.faceunity.com/developer/) 提供实时人像美化、美妆、滤镜 SDK；[官方更新](https://demo.faceunity.com/10590/news/chanpindongtai/11580.html) 列 Windows 和精细塑形。商业 SDK，许可另洽。 |
| 商汤 SenseTime | [SenseAR](https://www.sensetime.com/) 商业人像/AR SDK 的具体视频美颜功能与当前授权条款 unverified；需供应商确认，不作能力承诺。 |

## 结论 1：逐模块比较

| 模块 | 当前实现 | 最佳候选 | 建议及原因 |
|---|---|---|---|
| 风格/LUT | 程序生成 cube、肤色保护、bloom/finish | Colour + OCIO | 保留；借色彩空间和参考验证，OCIO 仅在需要标准色彩管理时引入。 |
| 参考追色 | 参考样本、皮肤分支 LUT | Reinhard/MKL；Neural Preset 作研究 | 保留；借统计对照，避免每帧重新估计导致闪烁；学习方法等待权重许可与跨帧验证。 |
| 磨皮/祛痘/眼下/去油/牙齿 | 局部 mask、heal 与 retouch GPU pass | GPUPixel 美颜；ABPN 研究 | 保留并借鉴；GPUPixel 基础磨皮不能证明覆盖全部语义、保痣和时序，ABPN 无可确认商用权重。 |
| 瘦脸/大眼 | landmark 控制的 GPU 位移场，RGB 与 mask 同步 | GPUPixel reshape / face-beautifier | 保留接口、先优化；借局部 shader 或对照替换原型，需保留多脸、遮罩对齐与时域稳定。 |
| 人脸与皮肤 | MediaPipe 478 点 + ONNX selfie 分割 | BiSeNet parsing | 保留；若五官遮罩不足，单独评估授权明确的 parsing 权重；InsightFace 官方模型商用受限。 |
| 时序 | One-Euro、mask EMA、形变场历史 | blind consistency / 光流 | 保留；借运动补偿和场景切换思想；后处理容易拖影、成本高。 |
| 预览/批量导出 | Qt、ffmpeg、同一 GL 链 | Shotcut/OBS | 保留；参考成熟交互，完整替换成本及许可负担高。 |

## 结论 2：GPUPixel 能否替换 warp / retouch？

**形变在技术上有可能替换，尚未证明可直接替换或更快。** GPUPixel Apache-2.0 源码可商用并须保留许可/NOTICE；具体版本第三方检测器、模型及素材另核验。优先复用其 reshape shader 算法，沿用现有 ModernGL pass 和 478 点追踪；将 MediaPipe 点映射至 GPUPixel 所需索引与坐标、验证坐标方向/比例与缺失点，不能假设两套索引相同。让同一逆向位移作用于 RGB、skin、mask 和所有 region，避免后续精修错位，保留多脸、转头衰减、失跟淡出、场景重置、历史稳定。

若试完整引擎，编译 Windows C++ DLL，用 pybind11/C ABI 包装；先证明 GL 版本、上下文线程归属、纹理共享、生命周期及同步可行，再测 CPU 上传/回读成本。无法共享时的逐帧拷贝可能抵消 GPU 收益；GPUPixel 检测器不是必须接入的前提。基础美颜可作为磨皮替代实验，但不能无证据替代祛痘、眼下、去油、牙齿和皮肤保护的全套流水线。

先在同一素材、分辨率和双脸/单脸情况下复现约 400 ms，分别计时 Python 控制点、uniform 上传、GL 提交、GPU timer query、同步和回读；异步 GPU 不能用提交时间冒充执行时间。对照开关形变的端到端 FPS/p50/p95，排除 shader 编译/首帧。验收包括默认零强度恒等、RGB/蒙版对齐、两脸与遮挡、发际和直线、转头、时序呼吸、预览与导出一致，以及主流 Windows GPU。上述为计划，非已测结果。

## 结论 3：潜在差异化

未发现一个**已核实可商用且开箱即用**的开源项目，完整同时覆盖参考图追色与独立肤色保护、可控局部精修、同步蒙版塑形、镜头级稳定、Windows 近实时和短视频批量工作流。单项算法、滤镜及基础美颜均已有公开实现；不能断言这些技术本身不存在开源实现。真正可形成差异的是整链效果、自然度、速度、跨脸型可靠性和可复现的质量验证。

## 结论 4：按价值/投入排序的三项行动

1. **最高：定位并修复 warp 400 ms**。分离 CPU、GPU 和同步耗时；借 GPUPixel / face-beautifier 局部形变公式做最小 GPU 原型，沿用现有 mask/时序接口。完成上面的几何与性能验收后再决定是否替换。
2. **高：建立参考追色和肤色保护对照集**。用 Reinhard/MKL、直方图和现有 LUT 在肤色、极端照明、场景切换素材上比较；控制色偏和闪烁，先复用方法而非未经授权代码。
3. **中：小规模评估细粒度人脸解析与磨皮**。用授权清晰的 BiSeNet 权重和 GPUPixel demo 分别测牙齿、眼下、发际及遮挡，记录 Windows DirectML/GL 实测耗时和闪烁；仅在质量收益超过集成成本时接入。
