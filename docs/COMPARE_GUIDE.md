# 用 PixCake / WinkStudio 结果做对比

1. 导出原视频指定时间的无损 PNG 帧：

   ```powershell
   python tools/export_frames.py input.mp4 --times 1,3,5 --out tools/results/frames
   ```

2. 在 PixCake 或 WinkStudio 中修饰导出的帧，并以 PNG 保存。保留原始分辨率，便于逐像素共用皮肤蒙版。
3. 用 Cake 处理同一张原始帧，输出 PNG。比较命令以原始图的人脸皮肤分割结果建立同一蒙版，再报告肤色 L、色相、Lab a/b、皮肤高频能量比例、暗斑 DoG 计数近似值和非皮肤 CIE76：

   ```powershell
   python tools/compare_reference.py original.png ours.png theirs.png --out tools/results/compare.jpg
   ```

输出表格中的 hueΔ 使用带符号圆周色相差；smooth% 是高斯 sigma 2 后的高频亮度能量相对原片的百分比。暗斑数是小暗斑的近似检测值，适合在同一原片上比较，不代表医学或绝对斑点计数。比较前须确保三张图同尺寸、同构图。
