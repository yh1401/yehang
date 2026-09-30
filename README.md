# 夜航 · 轻监测睡眠 App

以「手机传感器 + 鼾声识别 + 睡眠分期 + 晨间报告」为核心的轻监测睡眠应用，参照对象是睡眠岛。

当前交付物是一个**单文件 PWA**（纯静态 HTML/CSS/JS，无后端），可以直接装到手机主屏当 App 用。

- 线上地址：<https://yh1401.github.io/yehang/>
- 技术边界：GitHub Pages 只能托管静态资源，数据全部存在手机本地（localStorage / IndexedDB），不上云

## 目录结构

```
sleep/
├── docs/                        产品文档（先看这里）
│   ├── README.md                文档索引 / 阅读地图
│   ├── 01-市场调研.md            睡眠类 App 与小程序行业扫描
│   ├── 02-竞品拆解-睡眠岛.md      睡眠岛 9 大模块 + 技术/省电/隐私架构
│   └── 03-产品方案.md            我们的产品方案（实现进展见 §15）
├── web/                         ← 只有这个目录会被发布到线上
│   ├── index.html               站点入口（0 秒跳转到 mvp.html）
│   ├── mvp.html                 MVP 主程序（单文件 PWA）
│   ├── prototype.html           早期交互原型（设计参考，未发布为入口）
│   ├── sw.js                    Service Worker（cache-first 离线缓存）
│   ├── manifest.webmanifest     PWA 清单（可安装 / 独立窗口 / 图标）
│   ├── audio/                   四条音景循环（rain / ocean / piano / pink，各 60s）
│   ├── icon-*.png               应用图标
│   └── .nojekyll                关闭 Jekyll（否则下划线开头的文件会被吞掉）
├── tools/
│   └── make_loops.py            离线合成音景循环（numpy，输出到 web/audio/）
└── .github/workflows/
    └── deploy-pages.yml         推送到 main 时自动发布 web/ 到 GitHub Pages
```

**约定**：所有渲染用的资源都放在 `web/` 下、全部用相对路径引用（`./audio/...`），这样整个 `web/` 可以原样搬到任何静态服务器上，也保证 `https://yh1401.github.io/yehang/` 这个地址长期不变（已装到主屏的 PWA 不会失效）。

## 本地预览

```bash
cd web
python3 -m http.server 8788
# 浏览器打开 http://127.0.0.1:8788/
```

`index.html` 会自动跳到 `mvp.html`。注意：本地 `http.server` 不支持 Range 请求，音频仍可播放，但拿不到线上那种 `206` 分片响应。

## 部署

推到 `main` 分支即可，GitHub Actions 会自动发布 `web/` 目录：

```
push main  →  actions/upload-pages-artifact (path: ./web)  →  actions/deploy-pages
```

- 仓库 Settings → Pages 的 Source 必须是 **GitHub Actions**（不是分支发布）。之所以不能用「main 分支 / 根目录」发布，是因为分支发布只允许发布仓库根目录或 `/docs`，无法只发布 `web/`。
- 改了 `web/mvp.html` 后，记得同步升 `web/sw.js` 里的 `CACHE` 版本号，否则老用户会继续用缓存里的旧页面。
- 线上 CDN 有约 45 秒传播延迟，刚部署完看不到变化属正常。

### 音景音频的生成

四条循环音频由 `tools/make_loops.py` 离线合成（频域塑形白噪声 + 逆 FFT，天然无缝循环）：

```bash
python3 tools/make_loops.py    # 需要 numpy，输出到 web/audio/*.wav
```

## 产品文档

见 [docs/README.md](docs/README.md)。
