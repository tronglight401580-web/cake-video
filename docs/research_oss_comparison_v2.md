# 开源同类项目核验与 GPUPixel 实测（2026-11-14）
核验方法：GitHub 仓库页及 GitHub API `repos`、默认分支 `commits?per_page=1`；星数为查询时快照，日期为 UTC 提交日期；“活跃”仅指近一年有提交，不代表发布质量。下表链接为逐项来源；无许可文件或 GitHub 未识别许可证写“未声明”，不能据此复用代码。GitHub 镜像的许可证还须以项目上游为准。

| 原报告项目 | 许可证；星数；最后提交 UTC；维护判断 |
|---|---|
| [GPUPixel](https://github.com/pixpark/gpupixel) | Apache-2.0；2501；2026-09-26；活跃，但检测器另审 |
| [face-beautifier](https://github.com/ctbot000/face-beautifier) | MIT；0；2026-09-20；新项目，持续维护尚难判断 |
| [Beauty-Camera-AI](https://github.com/galaxeeranger/Beauty-Camera-AI) | 未声明；0；2026-06-10；新项目，持续维护未证实 |
| [FaceGlow](https://github.com/wangyifan349/FaceGlow) | MIT；1；2026-08-28；新项目，持续维护未证实 |
| [OBS](https://github.com/obsproject/obs-studio) | GPL-2.0；79593；2026-11-10；活跃 |
| [obs-beauty-filter](https://github.com/wuxiwuhen/obs-beauty-filter) | MIT；5；2026-09-02；新项目，持续维护未证实 |
| [Olive](https://github.com/olive-editor/olive) | GPL-3.0；9157；2024-12-05；近期未维护 |
| [Shotcut](https://github.com/mltframework/shotcut) | GPL-3.0；15684；2026-11-15；活跃 |
| [Kdenlive](https://github.com/KDE/kdenlive) | GPL-3.0；6111；2026-11-15；活跃 |
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | 项目以 LGPL-2.1-or-later 为主、可因构建变 GPL；67320；2026-11-14；活跃（GitHub 镜像许可证 API 为 NOASSERTION） |
| [OpenColorIO](https://github.com/AcademySoftwareFoundation/OpenColorIO) | BSD-3-Clause；2142；2026-10-01；活跃 |
| [VapourSynth](https://github.com/vapoursynth/vapoursynth) / [vs-denoise](https://github.com/Jaded-Encoding-Thaumaturgy/vs-denoise) | LGPL-2.1；2133；2026-11-10；活跃 / MIT；21；2025-11-05；已归档 |
| [AviSynth+](https://github.com/AviSynth/AviSynthPlus) / [脚本集](https://github.com/Asd-g/AviSynthPlus-Scripts) | 仓库 API 未识别（须核对各文件）；1221；2026-11-14；活跃 / 未声明；40；2026-08-09；活跃 |
| [Colour](https://github.com/colour-science/colour) | BSD-3-Clause；2694；2026-11-13；活跃 |
| [Reinhard color_transfer](https://github.com/jrosebr1/color_transfer) | MIT；519；2018-09-14；停止维护；2020 push 不等于默认分支提交 |
| [MKL colour_transfer](https://github.com/mahmoudnafifi/colour_transfer_MKL) | 未声明；27；2026-03-29；有近期提交但授权不清 |
| [Neural Preset](https://github.com/ZHKKKe/NeuralPreset) | 未声明；356；2023-09-07；近期未维护，权重另审 |
| [Deep Preset](https://github.com/minhmanho/deep_preset) | 未声明；110；2024-01-21；近期未维护，权重另审 |
| [ABPN](https://openaccess.thecvf.com/content/CVPR2022/papers/Lei_ABPN_Adaptive_Blend_Pyramid_Network_for_Real-Time_Local_Retouching_of_CVPR_2022_paper.pdf) / [Blind Video Temporal Consistency](https://perso.liris.cnrs.fr/nbonneel/consistency/) / [Learning Blind Video Temporal Consistency](https://arxiv.org/abs/1808.00449) | 原报告列的是论文或项目页，未给可识别的代码仓库；无可核验的 GitHub 星数/最后提交/代码许可，论文日期分别为 2022、2015、2018；仅作研究基线 |
| [face-parsing.PyTorch](https://github.com/zllrunning/face-parsing.PyTorch) | MIT 代码；2593；2019-05-18；停止维护，权重和数据另审 |
| [InsightFace](https://github.com/deepinsight/insightface) | 仓库 API 未识别，代码文件标 MIT；30226；2026-10-19；活跃，官方预训练模型限非商用研究 |
中文检索“美颜 开源 瘦脸 大眼 实时”“视频 磨皮 开源”补充：[CainCamera_](https://github.com/qinRight/CainCamera_) Apache-2.0、6 星、2019-09-29，停更且 Face++ 检测器需单独授权；[Camera-Special-Effect-Face-Reshape](https://github.com/CSsaan/Camera-Special-Effect-Face-Reshape) MIT、2 星、2024-11-07，近期未维护；[OBS 高级美颜滤镜](https://github.com/wtnl-zhi/obs-beauty-filter) GPL-2.0、2 星、2026-07-20，新项目且只做局部磨皮遮罩，尚非替代完整精修链。商业参考 PixelCake、Wink、CapCut、醒图、FaceUnity、SenseTime 维持原报告定位，不以产品宣传推断可复用代码。
## GPUPixel 源码机制与许可
`face_reshape_filter.cc` 每帧 CPU 设置宽高比、瘦脸/大眼强度、`hasFace` 和 106×2 浮点 uniform；没有 CPU 网格/面积约束/历史场。shader 对每像素依次对 9 对 `(3,44),(29,44),(7,45),(25,45),(10,46),(22,46),(14,49),(18,49),(16,49)` 做 `p -= (target-origin)*thinDelta*clamp(1-distance(p,origin)/distance(target,origin),0,1)`；随后在 `(74,72),(77,75)` 的 origin 周围，以 `5*distance(origin,target)` 为半径，做 `p=origin+(p-origin)*clamp(1-(1-(d/r)^2)*bigEyeDelta,0,1)`。归一化 y 除以宽高比，使距离在像素几何中各向同性。两步均为逆向采样；线性瘦脸核的支撑域到 target，眼核为二次径向权重，边缘位移归零。原版仅 `hasFace` 单组点，不处理双脸、遮罩同形变、转头/时序稳定或折叠。
`beauty_face_filter.cc` 是滤镜组：box blur 和 box high-pass 并行送 `beauty_face_unit_filter.cc`；模糊核半径默认 4、texel spacing 4，高通与平滑/美白/锐化在 shader 合成。平滑权重 `clamp((1-meanVar/(meanVar+0.1))*p*blurAlpha,0,1)`，`p=clamp((min(input.r,mean.r-0.1)-0.2)*4,0,1)`，随后加 8 邻域高通锐化与灰度/肤色/LUT 美白；CPU 每帧主要是传纹理和 uniform，无语义祛痘/眼下/牙齿。我们 `warp.py` 用 21 个轮廓点、2 个眼中心，CPU 做网格采样面积保护两次，再由 GPU 建半分辨率场、两次模糊、时域 EMA，并同步重映射 RGB/skin/mask/region；retouch/heal 有局部语义遮罩和独立处理，不能用该基础磨皮直接替换。
本地 `third_party/mars-face-kit` 仅头文件、预编译库和 `.mars_model`，没有单独 LICENSE/NOTICE；[上游许可澄清 issue #253](https://github.com/pixpark/gpupixel/issues/253) 仍在询问二进制及模型权利。原型只移植 Apache-2.0 shader 数学、使用现有 MediaPipe 模型，不执行/分发 Mars；若分发移植代码，保留 GPUPixel 版权、Apache-2.0 许可证和适用 NOTICE/修改说明，Mars 需独立书面确认。
## 1080×1920 对照与结论
独立原型见 `tools/proto/gpupixel_reshape.py`，MediaPipe→106 所需点映射在脚本 `JAW_MAP/EYE_MAP`（按几何近似而非官方同构表）；GPUPixel 强度薄脸 0.03、大眼 0.12，按单脸下颌约 3% 与本品 slim=eyes=1 调齐。单帧轮廓检测值“下颌缩小%/眼宽增加%/轮廓粗糙比”：hush 本品 2.80/3.11/0.987、原型 3.33/−2.08/0.974；indoor 3.61/5.00/0.988、原型 3.46/3.05/0.958；mother_child 两脸本品 4.76/3.82/0.978 与 3.18/2.52/0.990，原型 3.18/2.60/0.968 与 1.43/4.34/0.986。双脸输出按中心匹配检测，眼宽数字含重检噪声；原型眼中心及 contour 近似映射不等于 Mars 106 真值。
本品 hush 完整渲染 1185 ms、warp GPU 0.34 ms；cProfile 显示两次 `guard_controls` 合计 1171 ms（`displacement` 自身 1038 ms，`area_range` 98 ms），上传/读回约 4/4 ms，非 shader 瓶颈；单帧复测 indoor/mother_child 完整渲染 311/685 ms，warp GPU 0.27/0.35 ms。原型三帧总 CPU 11.8/10.5/9.3 ms，映射 0.1–0.2 ms、上传+uniform 3.9–6.3 ms、读回+同步 5.2–5.5 ms，GPU 0.36/0.36/0.69 ms（暖机后，单独 GPU 计时波动至 2.7 ms）；不是同等质量流水线，不能将速度比当产品加速比。120 帧 hush 的 jaw 位移（360 短边，与 `test_a` 时序口径相同）：本品均值 3.61 px、高通 std 1.709%、加速度 p95 0.865%；原型 3.93 px、0.696%、2.339%，其无历史稳定导致更大瞬时加速度。
以各自零强度输出作差，改变超过 2/255 的像素比例：脸框外至 18% 扩展框的近背景环（发丝/肩部/直线）hush 本品/原型 45.15%/55.87%，indoor 20.38%/43.32%，双脸 31.75%/37.15%；扩展框外远区为 3.586%/9.338%、0.103%/0.743%、0.441%/0.902%。近环平均最大通道差分别为 7.32/8.78、2.61/5.93、4.94/5.47；原型影响范围更大，尤其 indoor 水平线。远区最大单通道差为 75/106、98/100、73/63，含边缘纹理及采样极值，面积比例更适合比较范围。
**结论 1：逐模块比较。** 风格/LUT 与参考追色维持本品管线，以 Colour/OCIO/Reinhard/MKL 作色彩基准；磨皮/祛痘/眼下/牙齿维持语义 pass；瘦脸/大眼维持同步遮罩及历史场；解析优先现有 MediaPipe 与自拍分割；视频工作流借鉴 OBS/Shotcut，不嵌入其 GPL 代码。
**结论 2：GPUPixel 替换判断。** 保留本品 warp 数学及同步遮罩/多脸/时序结构，修复 CPU 面积保护开销；可借 GPUPixel 的 GPU 逆向坐标公式作优化试验，但其单脸核无折叠约束，眼及双脸一致性不足。审阅图 `tools/results/proto_reshape_review.jpg` 为三素材原图/本品/原型并列。
**结论 3：差异化。** 完整链路、自然度、跨帧可靠性和可复现验证仍有价值；不能宣称单项技术独占。
**结论 4：行动顺序。** 1 CPU 守卫优化；2 参考追色/肤色保护对照；3 授权清晰的人脸解析和磨皮小样。
