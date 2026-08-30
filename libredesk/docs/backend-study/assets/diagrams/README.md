# 图表资源

为避免 MarkText 在同一文档中渲染多张 Mermaid 图时出现画布叠加、布局错乱或本地 SVG 不显示，学习文档统一引用本目录中的静态 PNG。

- `.html` 是新版图表的可编辑源文件，使用手工布局的 SVG。
- `diagram-theme.css` 和 `diagram-runtime.js` 提供统一配色、节点、连线和文字规范。
- `.mmd` 是旧版 Mermaid 布局的备份，仅用于核对原始结构。
- `.png` 是 Markdown 实际引用的渲染结果。
- 修改图表源文件后，应重新生成同名 `.png`，不要把 `mermaid` 代码块直接放回主文档。

全部 11 张图均已按统一规范重新设计。画布不设固定宽高，由内容密度和连线路径决定；正文至少 14 px，实体框为文字保留足够内边距，阶段说明与连线必须使用不同的垂直空间。主文档中带 `-compact` 的 PNG 是显示版本；同名 `.mmd` 不能再用于覆盖新版 PNG。

## 导出 PNG

在本目录使用 Edge 的无头截图导出，截图尺寸必须与对应 HTML 中 `html, body` 的尺寸一致。例如 OTP 状态机当前使用更宽、更高的画布：

```powershell
& 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' `
  --headless --disable-gpu --hide-scrollbars `
  --window-size=980,620 `
  --screenshot=otp-state-machine.png `
  "file:///$((Resolve-Path .\otp-state-machine.html).Path -replace '\\','/')"

Copy-Item .\otp-state-machine.png .\otp-state-machine-compact.png -Force
```

导出后应按 Markdown 的常见显示宽度检查整图，而不能只检查原始像素尺寸。重点确认：文字不与线条相交、箭头不压入实体框、动作标签与条件标签各自占用独立空间、最外层路径没有贴住画布边缘。
