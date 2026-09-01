---
name: computer-use
description: |
  通过鼠标/键盘直接操控 Mac 桌面 GUI，适用于只能通过"人工操作屏幕"才能完成的任务：
  操作本地原生 App（微信、飞书、Figma 等）、爬取无 API 的桌面软件数据、
  自动化任何需要点击/输入/滚动的 GUI 流程。

  【重要：优先使用更专用的 skill，本 skill 是最后手段】
  - 任务涉及网页/浏览器 → 优先用 agent-browser skill
  - 任务涉及文件读写、代码执行 → 直接用内置工具
  - 只有目标是"无法通过 API 或其他工具访问的本地 GUI App"时，才使用本 skill

  典型触发场景：帮我爬飞书/微信群里的消息、帮我在 Figma 里点击某个元素、
  自动化某个桌面软件的 GUI 操作、截图分析当前屏幕状态。
compatibility:
  required:
    - "cliclick: brew install cliclick"
    - "macOS 辅助功能权限（System Settings → Privacy → Accessibility）"
    - "macOS 屏幕录制权限（System Settings → Privacy → Screen Recording）"
---

# Computer Use（macOS）

**工具组合**：`screencapture` + `cliclick` + `osascript` + Swift CGEvent（滚动）

> **先确认是否真的需要本 skill：**
> - 操作网页/浏览器 → 用 **agent-browser** skill，更稳定、更省 token
> - 读写文件、调用 API、执行脚本 → 直接用内置工具
> - 只有目标是**无 API 可用的本地 GUI App**（微信、飞书、Figma 等原生应用）时，才继续往下走

---

## 第一步：运行初始化脚本（每次任务开始执行一次）

```bash
bash <skill_dir>/scripts/init.sh
```

初始化做了三件事：
1. 检测 Retina 缩放因子，写入 `/tmp/_cu_scale`
2. 编译 Swift CGEvent 滚动工具到 `/tmp/_cu_scroll`
3. 安装截图辅助脚本 `/tmp/_cu_snap.sh`，并打印当前可见进程名

初始化后可用的命令：
| 命令 | 作用 |
|------|------|
| `/tmp/_cu_snap.sh out.png` | 截全屏（自动缩到逻辑分辨率） |
| `/tmp/_cu_snap.sh out.png W H x y` | 截图后裁剪到 W×H 区域（节省 token） |
| `/tmp/_cu_scroll x y amount` | 滚动（amount < 0 向下，> 0 向上） |
| `cat /tmp/_cu_scale` | 读取缩放因子 |

> `/tmp` 在重启后清空，重启后需重新运行初始化。

---

## 感知-行动循环

```
1. _cu_snap 截图 → Read 读取
   └─ 优先裁剪到目标区域：只截需要看的部分，大幅减少 token 消耗
2. 定位目标
   └─ 优先：AX 元素名（osascript）
   └─ 其次：截图坐标（cu_snap 输出已是逻辑坐标，直接用于 cliclick）
3. 执行操作
4. sleep 0.3~1.5s 等渲染 → 再截图确认
5. 重复直到完成
```

---

## 截图

```bash
/tmp/_cu_snap.sh /tmp/s.png              # 全屏
/tmp/_cu_snap.sh /tmp/s.png 900 600 0 300  # 裁剪：宽900 高600 从(x=0,y=300)开始
```

`cu_snap` 输出的图像坐标 == cliclick 逻辑坐标，**无需再做任何换算**。

---

## 鼠标操作

```bash
cliclick c:960,490     # 单击
cliclick dc:960,490    # 双击
cliclick rc:960,490    # 右键
cliclick p             # 打印当前坐标（调试）
```

> ⚠️ `cliclick dd:x,y` 是开始拖拽，不是滚动。

---

## 滚动

```bash
# 向下滚到底部
for i in $(seq 1 8); do /tmp/_cu_scroll 750 400 -20; sleep 0.05; done

# 向上滚
/tmp/_cu_scroll 750 400 5
```

> ⚠️ 聊天类 App（飞书、微信、Slack）的输入框会抢占键盘焦点，
> End / PageDown 键会打字到输入框里。必须用 `_cu_scroll`，不能用键盘。

---

## 输入文字

```bash
# 英文
osascript -e 'tell application "System Events" to tell process "AppName" to keystroke "hello"'

# 中文（直接 keystroke 会乱码，必须走剪贴板）
echo -n "你好世界" | pbcopy
osascript -e 'tell application "System Events" to tell process "AppName" to keystroke "v" using command down'
```

---

## 按键

```bash
cliclick kp:return   kp:esc   kp:tab   kp:delete   kp:arrow-down   kp:page-down
```

---

## 激活应用

```bash
osascript -e 'tell application "Feishu" to activate'
sleep 0.8
```

进程名必须用系统名，初始化时已打印进程列表。常见易错对：
- 飞书 → `Feishu`（不是 `Lark`）
- 微信 → `WeChat`

> ⚠️ 不要用 `set frontmost to true`——会报错 -10006。
> `activate` 已足够，如需置前可加 `set bounds of front window to {…}`。

---

## 点击 UI 元素（比坐标更准）

比截图估坐标更可靠的方式：通过 Accessibility 元素名直接点击。

```bash
# 按名称点击按钮
osascript -e 'tell application "System Events" to tell process "App" to click button "OK" of window 1'

# 先查有哪些可点元素
osascript -e 'tell application "System Events" to tell process "App" to get every UI element of window 1'
```

---

## 等待窗口就绪

```bash
osascript << 'EOF'
tell application "App" to activate
tell application "System Events"
    tell process "App"
        set w to 0
        repeat until (count of windows) > 0 or w > 10
            delay 0.3
            set w to w + 0.3
        end repeat
    end tell
end tell
EOF
```
