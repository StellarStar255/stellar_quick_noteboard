# Undo/Redo 重构记录 (2026-03-19)

## Bug 描述
Undo 操作（Cmd+Z）非常卡顿，即使只是撤销一个字符也会明显卡一下，同时页面会自动跳转到其他位置。

## 根因分析

### 旧架构的问题
旧的 undo 实现是「全量快照 + 全量重建」模式：

```
按键 → on_key_press() → save_undo_state() → get_content_with_markers()
                                               ↑ 遍历所有 tag，dump 全文 (~50-200ms)

Cmd+Z → undo() → get_content_with_markers()   → 保存当前状态到 redo 栈
                → restore_content()
                    → text_area.delete("1.0", END)   → 清空编辑器
                    → load_content_with_images()      → 从头重建全部内容
                        → 重新插入所有图片 (PIL resize + PhotoImage)
                        → 重新插入所有视频缩略图 (PIL + qlmanage)
                        → 重新插入所有文件链接
                        → apply_markdown_formatting()  → 正则扫描全文 + 设置 tag
                    → text_area.see(cursor_pos)        → 页面跳转！
```

即使只撤销一个字符，也要执行全部流程，耗时 200ms+。

### 额外性能问题
- `on_key_press()` 每次按键都调用 `save_undo_state()`（带 500ms 去抖），而 `save_undo_state()` 内部调用 `get_content_with_markers()` 遍历所有 tag
- 视频缩略图增加了额外开销：即使有磁盘缓存，每次重建仍需 PIL Image.open → resize (LANCZOS) → ImageTk.PhotoImage 转换

## 修复方案

### 新架构：Tk 原生优先 + 自定义栈兜底

```
普通打字/删除 → Tk 自动记录 (autoseparators=True)
Cmd+Z → undo():
    1. 尝试 edit_undo()  → 成功：瞬时完成，仅 schedule markdown 刷新
    2. TclError (原生栈空) → 尝试自定义栈 → restore_content() 全量重建

粘贴图片/文件 → save_undo_state():
    1. edit_reset()  → 刷新原生栈（将之前的文字编辑合并到快照）
    2. get_content_with_markers() → 保存全量快照
    3. 执行粘贴操作
```

### 具体改动

| 方法 | 改动 | 原因 |
|------|------|------|
| `undo()` | 优先 `edit_undo()`，失败再用自定义栈 | 文字撤销瞬时完成 |
| `redo()` | 优先 `edit_redo()`，失败再用自定义栈 | 同上 |
| `on_key_press()` | 移除 `save_undo_state()` 调用 | Tk 原生自动跟踪，不再需要 |
| `on_before_delete()` | 移除 `save_undo_state()` 调用 | 同上 |
| `save_undo_state()` | 开头加 `edit_reset()` | 刷新原生栈，避免两套系统冲突 |
| `restore_content()` | 末尾加 `edit_reset()` | 全量重建不应进入原生撤销栈 |
| `restore_content()` | `see()` → `yview_moveto()` | 保持滚动位置，不跳转 |
| `load_notes()` | 末尾加 `edit_reset()` | 加载笔记不可撤销 |
| 笔记切换 | 加 `edit_reset()` | 同上 |

### 视频缩略图优化

| 层级 | 缓存 | 命中场景 |
|------|------|----------|
| `self.images[vidthumb_id]` | PhotoImage (最终渲染对象) | undo/redo 重建时直接复用 |
| `self._video_thumb_cache` | PIL Image (内存) | 同一会话内重新插入 |
| `_thumb_{filename}.png` | PNG 文件 (磁盘) | 关闭后重新打开 |
| `_generate_video_thumbnail()` | qlmanage + mdls | 首次粘贴视频 |

## 关键设计决策

### 为什么不完全用 Tk 原生 undo？
Tk 原生 undo 不跟踪 `tag_add`/`tag_remove`。粘贴图片/文件后，undo 会移除嵌入的图片字符和文件名文字，但不会恢复 `icon_`/`file_`/`imgtag_` 等 tag。这导致：
- 点击事件失效
- `get_content_with_markers()` 找不到 tag，序列化丢失文件标记

所以复杂操作（涉及 tag 的）仍需自定义栈做全量快照/恢复。

### 两套系统如何共存？
- `save_undo_state()` 调用 `edit_reset()` 刷新原生栈
- 这样 undo 时，原生栈只包含「自上次快照以来的文字编辑」
- 原生栈耗尽后，下一次 undo 才走自定义栈

### 时序示例
```
用户操作：粘贴图片 → 输入 "abc" → 输入 "def" → Cmd+Z × 4

1. 粘贴图片:
   save_undo_state() → edit_reset() + 快照 S0 入栈
   执行粘贴 (Tk 原生记录了粘贴操作，但随后被 edit_reset 清除)

2. 输入 "abc": Tk 原生记录 insert "a", "b", "c"
3. 输入 "def": Tk 原生记录 insert "d", "e", "f"

4. Cmd+Z #1: edit_undo() → 撤销 "def" (瞬时)
5. Cmd+Z #2: edit_undo() → 撤销 "abc" (瞬时)
6. Cmd+Z #3: edit_undo() → TclError (原生栈空)
              → 自定义栈 pop S0 → restore_content() (全量重建，恢复到粘贴前)
7. Cmd+Z #4: edit_undo() → TclError, 自定义栈也空 → 不操作
```

## 验证清单
- [x] 普通打字后 Cmd+Z 瞬时撤销，无卡顿
- [x] 粘贴图片后 Cmd+Z 可撤销（走自定义栈）
- [x] 粘贴视频后 Cmd+Z 可撤销
- [x] 删除线操作可撤销
- [x] 切换笔记后 Cmd+Z 不会撤销到上一本笔记的内容
- [x] 页面不会在 undo 时自动跳转
