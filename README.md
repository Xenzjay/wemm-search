# WeMM Search

一个简单的本地文件语义搜索工具。

你只需要：

1. 双击启动入口。
2. 在网页中选择一个文件夹。
3. 点击“开始索引”。
4. 输入自然语言搜索文件。

## 位置

```text
E:\AIProject\wemm-search
```

## 第一次安装

第一次使用时，双击：

```text
scripts\setup.bat
```

安装程序会完成：

- 创建 Python 虚拟环境
- 安装 CUDA 版 PyTorch
- 安装文档、图片和向量检索依赖
- 检查并创建项目目录
- 尝试创建桌面快捷方式

如果模型文件还没有下载，再双击：

```text
scripts\download-model.bat
```

模型约占数 GB，只需要下载一次。

## 平时使用

双击：

```text
scripts\start.bat
```

浏览器会自动打开：

```text
http://127.0.0.1:8876
```

网页中的操作只有三步：

1. 点击“选择文件夹”。
2. 点击“开始索引”。
3. 在搜索框输入内容并按回车。

搜索结果会按图片、文档、表格和其他文件分类展示，并显示内容摘要。

每条结果提供：

- 预览：文本、Markdown、代码、Word、Excel 显示文字；图片直接预览；PDF 在网页中打开。
- 打开文件：使用运行服务的 Windows 电脑上的默认程序打开文件。
- 打开文件夹：在运行 WeMM Search 服务的 Windows 电脑中打开资源管理器，并定位到该文件。
- 复制路径：复制完整文件路径。

图片结果会直接显示缩略图。检索排序会优先考虑文件名和摘要中的关键词命中，再补充达到最低相关度的语义结果；仅仅因为目录路径包含关键词的文件不会直接列入结果。

搜索词如果直接出现在文件名、路径或文字摘要中，会用高亮标出，并显示“关键字位置”。只有语义相关、没有出现原词的结果会标记为“语义相关”。

如果从其他设备访问网页，预览内容会通过运行服务的电脑提供；“打开文件夹”也会在服务所在电脑上执行。

## 停止和重启

停止服务：

```text
scripts\stop.bat
```

重启服务：

```text
scripts\restart.bat
```

查看状态：

```text
scripts\status.bat
```

## 索引说明

首版支持：

- TXT
- Markdown
- PDF
- Word
- Excel
- JPG/JPEG
- PNG
- WEBP
- BMP

第一次索引图片时，程序需要加载 WeMM-Embedding-2B，可能需要几十秒。模型加载完成后，页面会显示：

- 当前阶段
- 当前进度
- 当前处理文件
- 已处理数量

图片会先缩小到适合显存的尺寸，再交给模型处理。你的 RTX 4060 Ti 8GB 使用默认配置即可。

原始文件只读，不会被移动、重命名或修改。

## 支持的预览

网页预览与索引范围略有区别：

- 图片：JPG、JPEG、PNG、WEBP、BMP、GIF、TIFF
- 文本：TXT、Markdown、CSV、TSV、JSON、XML、HTML、CSS、JavaScript、TypeScript、Python、Java、Go、Rust、C/C++、C#、PHP、Shell、PowerShell、SQL、YAML、TOML、INI、LOG 等
- 文档：PDF、DOCX、PPTX、RTF、ODT、ODS、ODP、EPUB
- 表格：XLSX
- 目录类文件：ZIP、RAR、7Z、ISO，以及视频、音频、PSD、AI 等文件可建立文件记录并按文件名、路径检索；暂不对其中的二进制内容生成语义向量

新增加的文件格式需要点击网页中的“重新索引”后才会进入索引。

图片语义检索依赖 WeMM 模型对图片内容生成的向量。为了减少误召回，纯语义图片结果使用比普通文档更高的相关度门槛，并限制最多补充少量结果；关键词直接命中仍然优先。

其他类型仍然可以出现在索引配置允许的范围内，但网页只显示文件信息，并提供打开文件夹入口。

## 数据位置

```text
data\       索引文件和向量数据库
cache\      图片预处理缓存
logs\       服务日志
models\     模型文件
config\     配置文件
```

索引和缓存默认保存在项目目录，不会修改原始文件。

## 可选维护入口

手动提交增量索引：

```text
scripts\index.bat
```

手动提交初次索引：

```text
scripts\index.bat --initial
```

备份索引和配置：

```text
scripts\backup.bat "E:\Backups\wemm-search"
```

日常使用不需要执行这些入口，直接使用 `start.bat` 和网页即可。

## 常见问题

### 双击后窗口一闪而过

用 `scripts\status.bat` 查看服务状态。如果启动失败，检查：

```text
logs\service.log
logs\service.err.log
logs\service.out.log
```

### 浏览器打不开

先双击：

```text
scripts\status.bat
```

确认服务地址是：

```text
http://127.0.0.1:8876
```

如果 8876 端口被其他程序占用，修改：

```text
config\config.json
```

中的：

```json
"port": 8876
```

同时把 `scripts\start.ps1`、`scripts\status.ps1` 和 `scripts\index.ps1` 中的端口改成同一个值。

### 图片索引很慢

第一次索引需要加载模型，首次等待属于正常情况。后续图片会使用本地预处理缓存。

### 图片索引失败

优先检查：

- 图片是否能正常打开
- 文件夹是否有读取权限
- 磁盘剩余空间
- `logs\service.log` 中的错误信息

重新点击网页中的“重新索引”即可再次处理。

## PowerShell 文件

`.ps1` 文件是底层维护脚本，BAT 文件是给日常使用的入口。普通使用者只需要记住：

```text
setup.bat          第一次安装
download-model.bat 下载模型
start.bat          启动
stop.bat           停止
restart.bat        重启
status.bat         查看状态
```
