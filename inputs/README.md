# inputs

这里放**不能进仓库但构建必需**的输入。

## 必放（Release 资产）

把 2 GB 基础 SD 镜像压缩后上传到 Release（tag: `inputs`）：

- `base-sd512-a7z.img.xz`（约 104 MB）
- 解压后 SHA256: `977EDDFE9F9895D1DD9FFE991C0A9568BCD3B0FAB69F6B509ADE370DA6995EFF`

``bash
gh release create inputs --title 'pinned build inputs' --notes 'A7Z base SD image'
gh release upload inputs base-sd512-a7z.img.xz
``n
## 可选

- `systemd-timesyncd_255.4-1ubuntu8.17_arm64.deb` —— 已经提取进 `overlay/`，保留一份便于核对。

