# 架构与扩展指南

本文描述当前实现；实际代码是最终依据。

## 模块地图

目标依赖方向是 `ui → pipeline → render/analysis → color/io → core`。
这是分层约定，不代表现有代码严格满足每一条边：预览直接调用渲染、分析和 IO，部分模块通过旧路径兼容导入。
`core` 不依赖其他 cake 包；外部库和 Python 标准库不计入该方向。

- `cake/core`：`Recipe`、`RetouchCfg`、pass 注册、事件总线和配置常量。
- `cake/io`：`probe` 获取媒体信息；`media` 封装 ffmpeg 解码、编码、尺寸和编码器选择。
- `cake/color`：`cube` 读写 LUT，`looks` 生成 LUT，`styles` 加载风格，`refcolor` 生成参考图风格。
- `cake/analysis`：`Analyzer` 调度进程或线程，`models` 负责模型，`segment` 负责分割，`layers` 和 `frames` 处理人脸数据。
- `cake/render`：`Renderer` 编排阶段，`RenderContext` 管理 OpenGL，`FrameContext` 存放逐帧状态和纹理。
- `cake/render/passes`：各 GPU 阶段自注册，`__init__` 导入内置阶段。
- `cake/pipeline`：`export.grade_video` 协调完整视频导出；`stills` 处理图片。
- `cake/ui`：`MainWindow` 组合参数、队列和预览；`PreviewEngine` 在 QThread 运行；`ExportWorker` 执行导出。
- `cake/cli.py`：命令行解析和调度；`cake/__main__.py` 是 `python -m cake` 和 `cake` 入口。
- 顶层 `cake/gpu.py`、`face.py`、`media.py` 等为兼容转发模块；新代码优先使用对应分层路径。

## Recipe：参数总线

`cake/core/recipe.py` 的 dataclass 可通过 `to_dict`、`from_dict` 序列化和恢复。
字段元数据包含 label、default、range、min、max、step、ui 和 preview_only；参数面板据此生成控件。

| 字段 | 默认值 | 约束及含义 |
|---|---:|---|
| `style` | `none` | 非空风格名 |
| `strength` | 1 | 0–1.5，风格强度 |
| `retouch.level` | 0.5 | 0–1，精修强度 |
| `retouch.spots` | None | None 或 0–1，祛痘 |
| `retouch.eyes` | None | None 或 0–1，黑眼圈 |
| `retouch.keep_moles` | True | 保留痣 |
| `retouch.debug` | False | 仅预览检测标记 |
| `skin_protect_scale` | 1 | 0–1.25，皮肤 LUT 权重比例 |
| `demo_tint` | 0 | 0–1，示例色调；默认关闭 |
| `version` | 1 | 正整数，当前格式版本 |

`validate` 检查类型、有限数和范围；`for_export` 复制参数并清除 debug。
`from_dict` 接受嵌套 retouch；旧式数值 retouch 经 `from_legacy` 转换，`opts.under` 映射 eyes，旧 skin_protect 除以 0.8。
版本号当前只校验和存储，并没有按版本号自动迁移的分支。
UI 参数、预设及队列设置保存字典；预览和导出分别重建 Recipe，传入 `Renderer.apply_recipe`。

## Pass 注册与纹理

`core.registry.Pass` 提供 `setup(gl,width,height)`、`enabled(recipe,frame_ctx)`、`run(frame_ctx)`、`release()`。
`@register_pass(name, order)` 注册类，名称不能重复；按 order、name 排序。
`stage` 默认 frame；face 阶段由 `set_face` 调用，frame 阶段由 `render` 调用。
`reads`/`writes` 是约定和说明，当前注册器不校验依赖，也不自动分配纹理。

| 顺序 | 阶段 | 时机 | 声明的读取 → 写入 |
|---:|---|---|---|
| 100 | input | frame | 输入帧 → rgb |
| 200 | maskbuild | face | seg_a、seg_b、layers → mask、skin |
| 250 | warp | 预留 | 尚未实现 |
| 300 | heal | frame | rgb、mask → healed |
| 400 | retouch | frame | rgb、healed、mask → retouched |
| 500 | grade | frame | rgb、retouched、skin → graded |
| 600 | bloom | frame | graded → bloom |
| 650 | demo_tint | frame | graded → graded |
| 700 | finish | frame | graded、bloom → out8 或 out16 |
| 800 | output | frame | out16 → nv12 |

maskbuild 从 face 分析结果上传分割和 layers，构造 mask、skin；上述输入名称是声明，并非都由其他 pass 写入纹理字典。
heal/retouch 可能关闭，grade 有原始 rgb 回退；bloom 关闭时 finish 使用零纹理。
finish 的 out8 路径直接回读 RGB；out16 供 output 转换 NV12。
output 的 NV12 平面经同步或双缓冲 PBO 读回；`flush` 取回最后一帧。

## 事件总线

`core.bus.EventBus` 使用锁保护订阅列表，同步调用订阅者；`subscribe` 返回取消订阅函数。
导出发布 `log(message)`、`progress(done,total)`、`status(status='started',input,output)`、`status(status='completed',frames,seconds,fps,out)`。
UI 导出失败发布 `error(message,input)`；异常不是自动转换成总线事件。
`ui.bus_qt.QtBusBridge` 将 status、progress、error 包成 dict 信号；关闭时取消订阅。
Qt 跨线程连接负责把信号送到接收者线程；log 不在该桥接列表中。

## 配置中心

`core/config.py` 在导入时读取环境，改变环境后需重新启动进程。

| 名称 | 默认 | 用途 |
|---|---|---|
| APPDATA | 用户 home | 预设路径 `<APPDATA>/cake/presets.json` |
| CAKE_SEG | auto | 分割后端；cpu 可强制 CPU |
| CAKE_ANALYZER | process | 分析模式；thread 可切换线程 |
| CAKE_YUV | 未设置 / False | 仅值 `1` 开启 YUV 输入路径 |
| ROOT | 仓库根目录 | 数据文件根路径 |
| MODEL_DIR / LUT_DIR / STYLE_DIR | 根目录下 models / luts / styles | 模型与风格资源 |
| SEGMENTATION_MODEL | models/selfie_multiclass_256x256.onnx | GPU 分割模型 |
| ANALYSIS_SHORT | 360 | 分析短边 |
| SEG_EVERY | 2 | 分割间隔 |
| PROCESS_WORKERS | 3 | 分析进程数 |
| THREAD_WORKERS | 4 | 分析线程数 |
| PREVIEW_SHORT | 720 | 预览短边 |
| LOOKAHEAD | 6 | 预览预读帧数 |
| ENCODERS | nvenc、hevc、mf、x264 | 编码参数表；具体参数见 config.py |

导出还接受 max_short（默认 1080）、encoder（auto）、tonemap（mobius）等函数/CLI 参数；它们并非环境变量。
模型需要单独下载；README 中列出地址和 ONNX 转换方式。ffmpeg 与 ffprobe 需在 PATH 中。

## 数据流

导出：probe 获取视频信息，Decoder 由 ffmpeg 解码；按需要 Analyzer 预读并异步分析。
主线程取得当前帧的分析结果，调用 `set_face` 构造 mask 和 skin，再按顺序执行 frame passes。
finish 输出高精度纹理，output 转 NV12，双 PBO 管线返回前一帧；末尾 flush。
写线程把结果送 Encoder，最终复用/处理音频；无分析需求时跳过分析。
导出将 `debug` 清零。输入 YUV 直通是可选路径，默认解码 RGB。

预览：UI 将 load、seek、recipe 等命令送 `PreviewEngine` 的队列。
引擎线程按预览尺寸解码并预读，必要时分析，调用相同 Renderer。
预览读取 RGB 并发出处理图、原图和时间信号；暂停时参数变化重绘当前帧。
预览保留 debug，并用定时器合并快速滑块变化。

## 如何新增一个效果

本仓库的 `demo_tint` 是完整例子：

1. 在 Recipe 增加 0–1 的 `demo_tint` 和 UI 元数据，默认 0，并加入 validate。
2. 在 `render/passes/demo_tint.py` 注册 order 650 的 `DemoTint`。
3. `enabled` 仅在值大于 0 时返回真；默认不执行，保证基线不变。
4. setup 创建 shader 和独立目标纹理；run 读取 graded，混入暖色并写回 graded 槽。
5. release 释放该 pass 的纹理及 framebuffer。
6. 在 passes 包导入模块，确保注册；参数面板通过元数据生成滑块。
7. 在预览和导出中传递参数，测试开启改变输出，关闭恢复逐字节相同。

注意：例子在 bloom 之后修改 graded，所以 bloom 已由未加色调的 graded 计算。
避免同时读取与写入同一 OpenGL 纹理；使用独立目标再替换槽。

## 并行开发约定与验证

新效果拥有自己的 pass、相应测试和文档；共享变更限 Recipe 字段、pass 注册导入和必要的 UI 元数据/参数传递。
避免改其他效果的 shader 和共享编排；新顺序先与已有编号核对，250 留给未来 warp。
加入可独立运行的 `tests/test_*.py`，使用无参数 `test_` 函数以兼容 `tests/run_unit.py`。
图形/UI 测试可使用 `QT_QPA_PLATFORM=offscreen`；验证关闭时逐字节不变和开启时效果生效。

```powershell
python tools/golden.py check
python tests/run_unit.py
python tools/test_ui.py
python tools/run_all_tests.py
python tools/test_refcolor.py
python tools/bench_speed.py samples/street_mixed_1227.mp4
```

只有有意改变输出并完成审查后才运行 `python tools/golden.py record`；在变更说明记录原因和预期差异。
不要为通过检查而覆盖 golden。全量回归耗时较长，结果日志写入 `tools/results`。

## 资源与运行边界

- `styles/*.json` 保存风格参数与 LUT 引用。
- `luts/` 存放 LUT；参考图生成也会写入风格及 LUT。
- `models/` 存放单独下载的模型，不由 Python 安装自动获取。
- `samples/` 是回归和性能测试素材。
- `tools/results/` 保存测试日志及图片。
- `tools/golden.py` 管理 golden 基线。
- `tools/bench_speed.py` 测量处理吞吐量。
- `tools/test_refcolor.py` 检查参考图追色。
- `tools/test_ui.py` 运行桌面界面场景。
- `tools/run_all_tests.py` 汇总多类端到端测试。
- `tests/run_unit.py` 不依赖 pytest 的测试发现机制。
- 图形渲染需要可用的 OpenGL 3.3 上下文。
- DirectML 分割依赖支持的系统、运行库和 ONNX 模型。
- 缺少 GPU 分割模型时可回退 CPU 分割。
- 编码器按系统支持情况选择，实际速度取决于硬件。

## 参数流和生命周期细节

- 队列每一项保存独立设置字典及输入路径。
- 改变当前参数后，UI 将设置同步给预览引擎和当前队列项。
- 应用到全部会更新队列中每一项。
- 保存预设将设置写入配置的预设文件。
- 导出从队列设置构造 Recipe 的副本。
- `for_export()` 不修改原有的预览 Recipe。
- `Renderer.apply_recipe` 验证 Recipe，再配置风格与精修。
- Renderer 保留 Recipe 副本，供 pass 判断是否启用。
- face 阶段得到的 mask 和 skin 跨帧保存，直到再次更新。
- frame 阶段从保存的 mask 和 skin 初始化纹理槽。
- 每帧创建新的 FrameContext，避免复用上一帧的结果字段。
- `FrameContext.uniforms` 还保存风格及通用渲染参数。
- `FrameContext.result` 存储本次 readback 的字节或 None。
- 顺序数相同时按注册名称排序。
- Pass 生命周期从 setup 到 release；纹理由所属阶段管理。
- 示例效果使用固定暖色乘子，滑块控制混合比例。
- demo_tint 为零时不执行该 pass，因此不会引入额外量化。
- UI 的肤色保护仅在当前风格有 skin LUT 时可操作。
- 无 skin LUT 时 grade 不应用皮肤 LUT 权重。

## 回归结果的阅读方法

- golden 比较输出帧与已记录基线。
- 新效果默认关闭时，golden 应继续通过。
- 单元测试覆盖参数迁移、注册与渲染行为。
- UI 测试检查预览、队列、预设和导出流程。
- 全量回归还包含 YUV 路径、CLI 样片及分割一致性。
- 分割一致性脚本记录已知差异，需查看结果详情。
- 性能测试同时报告处理循环和包含启动时间的速度。
- 并行运行重负载测试会影响速度数字。
- 测试生成文件不等同于新的 golden 基线。
- 修改基线之前应检查输出差异并说明业务原因。
