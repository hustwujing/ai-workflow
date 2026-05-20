# ai-workflow 自升级功能

## 功能说明

ai-workflow 现在支持一键自升级到最新版本，无需手动执行 `git pull` 和 `pip install`。

## 使用方法

```bash
ccg upgrade
```

## 工作流程

1. **检查安装方式**：确认 ai-workflow 是通过 `git clone` 安装的
2. **检查本地修改**：如果有未提交的修改，会提示用户确认是否继续
3. **拉取最新代码**：执行 `git pull origin <current-branch>`
4. **重新安装**：执行 `pip install -e .` 重新安装依赖
5. **显示更新日志**：展示最近 5 个提交记录

## 前置条件

- ai-workflow 必须通过 `git clone` 安装（不支持 pip 安装的版本）
- 需要网络连接以拉取远程代码
- 需要有 git 仓库的访问权限

## 示例输出

```bash
$ ccg upgrade
[upgrade] 检查 ai-workflow 安装方式...
[upgrade] 发现 git 仓库：/path/to/ai-workflow
[upgrade] 当前分支：main
[upgrade] 拉取最新代码...
Already up to date.
[upgrade] 重新安装依赖...
Obtaining file:///path/to/ai-workflow
Installing collected packages: ai-workflow
Successfully installed ai-workflow

[成功] ai-workflow 已升级到最新版本。

最近的更新：
  9578279 feat: 日报各 Issue 展示提出日期（MM-DD）
  401f949 Revert "feat: 日报「新提出」改为「待认领」，并展示提出时间"
  b0c7b98 Revert "feat: 日报新增「待上线」状态，修复 pre 合并后退回待认领的问题"
  f63bc2e feat: 日报新增「待上线」状态，修复 pre 合并后退回待认领的问题
  4b4249c feat: 日报「新提出」改为「待认领」，并展示提出时间
```

## 错误处理

### 非 git 安装

```bash
[错误] ai-workflow 不是通过 git clone 安装的，无法自动升级。
  请手动重新安装：
    git clone <repo-url>
    cd ai-workflow
    pip install -e .
```

### 有未提交的修改

```bash
[警告] 检测到未提交的本地修改：
 M cc/main.py
  升级可能会覆盖这些修改，建议先提交或暂存。
是否继续升级？(y/N):
```

### git pull 失败

```bash
[错误] git pull 失败，请检查网络连接或手动执行 git pull。
```

### pip install 失败

```bash
[错误] pip install 失败，请检查 Python 环境。
```

## 注意事项

1. **本地修改会被覆盖**：如果有未提交的修改，升级前会提示确认
2. **需要网络连接**：升级过程需要访问 git 远程仓库
3. **当前分支**：会拉取当前所在分支的最新代码（通常是 `main`）
4. **依赖更新**：如果有新的依赖，会自动安装

## 手动升级（备选方案）

如果自动升级失败，可以手动执行：

```bash
cd /path/to/ai-workflow
git pull origin main
pip install -e .
```
