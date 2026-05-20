# 分支命名规范更新

## 新的分支命名规则（Git Flow 风格）

从旧的 `issue_<id>` / `hotfix_<id>` 格式升级为更规范的 Git Flow 风格：

| 旧格式 | 新格式 | 示例 |
|-------|--------|------|
| `issue_123` | `feature/<id>-<desc>` | `feature/123-user-login` |
| `hotfix_456` | `hotfix/<id>-<desc>` | `hotfix/456-payment-fix` |

## 优势

✅ **避免中文**：描述部分只包含 ASCII 字母、数字、`-`  
✅ **长度可控**：描述自动截断到 30 字符  
✅ **符合规范**：遵循业界标准 Git Flow 命名  
✅ **可读性强**：一眼看出分支类型和功能  
✅ **向后兼容**：旧格式分支仍然可以正常工作  

## 自动生成规则

系统会**优先使用 LLM** 将 Issue 标题转换为英文 slug（如果配置了 `LLM_API_KEY`），失败或超时（15秒）则回退到基于规则的提取。

### LLM 生成（推荐）

配置 LLM 后，即使是纯中文标题也能生成有意义的英文描述：

```
Issue 标题: 用户登录优化
生成分支: feature/123-user-login-optimization

Issue 标题: 修复支付页面崩溃问题
生成分支: hotfix/456-fix-payment-crash

Issue 标题: 添加商品搜索功能
生成分支: feature/789-add-product-search
```

**配置方法**：在 `.env` 文件中添加：
```bash
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1  # 可选，默认 OpenAI
LLM_MODEL=gpt-4o-mini  # 可选，默认 gpt-4o-mini
```

### 规则提取（回退方案）

LLM 未配置或调用失败时，使用规则提取英文部分：

#### 英文标题
```
Issue 标题: User Login Optimization
生成分支: feature/123-user-login-optimization
```

#### 中文标题
```
Issue 标题: 用户登录优化
生成分支: feature/123  (纯中文无法生成描述，只用 ID)
```

#### 混合标题
```
Issue 标题: [需求]Payment支付功能优化
生成分支: feature/123-payment  (提取英文部分)
```

#### 特殊字符处理
```
Issue 标题: 【紧急】修复iOS崩溃问题
生成分支: hotfix/456-ios  (移除特殊符号，保留英文)
```

## 使用方法

### 创建功能分支
```bash
ccg gitlab feature start 123
# 自动创建：feature/123-<desc>
```

### 创建热修分支
```bash
ccg gitlab hotfix start 456
# 自动创建：hotfix/456-<desc>
```

## 兼容性

### 旧分支仍然可用

所有现有的 `issue_*` 和 `hotfix_*` 分支仍然可以正常工作：
- ✅ 可以继续开发
- ✅ 可以创建 MR
- ✅ 可以合并
- ✅ 所有检查和门禁正常工作

### 检测逻辑

系统会同时识别新旧两种格式：

```python
# 功能分支检测
feature/123-user-login  ✓
issue_123               ✓

# 热修分支检测
hotfix/456-payment-fix  ✓
hotfix_456              ✓
```

## 迁移建议

### 新分支使用新格式

从现在开始，所有新创建的分支都会使用新格式：
- 通过 `ccg gitlab feature start` 创建的分支自动使用新格式
- 通过 `ccg gitlab hotfix start` 创建的分支自动使用新格式

### 旧分支无需迁移

已存在的旧格式分支：
- **不需要重命名**
- 继续使用直到合并完成
- 合并后自然淘汰

### 手动创建分支

如果需要手动创建分支（不推荐），请遵循新格式：

```bash
# 功能分支
git checkout -b feature/123-user-login

# 热修分支
git checkout -b hotfix/456-payment-fix
```

**注意**：
- 描述部分只能包含小写字母、数字、`-`
- 不要使用中文、空格、特殊字符
- 多个单词用 `-` 连接

## 常见问题

### Q: Issue 标题是中文怎么办？

A: 
- **配置了 LLM**：系统会自动将中文标题翻译为英文 slug（如 "用户登录优化" → `user-login-optimization`）
- **未配置 LLM**：系统会尝试提取英文部分。如果完全没有英文，分支名会退化为 `feature/123`（只有 ID）

推荐配置 LLM 以获得更好的分支命名体验。

### Q: 旧分支需要重命名吗？

A: 不需要。旧格式分支仍然完全支持，可以继续使用直到合并完成。

### Q: 如何确保描述部分合规？

A: 系统会自动处理：
- **LLM 生成**：提示 LLM 只输出小写字母、数字、连字符，并在返回后再次清理
- **规则提取**：移除中文字符、移除特殊符号、转换为小写、合并连续的 `-`、截断到 30 字符
- **超时保护**：LLM 调用超时 15 秒后自动回退到规则提取

### Q: 可以自定义描述吗？

A: 当前版本自动从 Issue 标题生成。如果需要自定义，可以手动创建分支（但要确保格式正确）。

## 技术细节

### ai-workflow 修改

- `cc/branch.py` - 更新分支创建和检测逻辑
- 兼容新旧两种格式

### ai-gitlab-hook 修改

- `app/handlers.py` - 更新所有分支检测逻辑
- 添加辅助函数：`_is_feature_branch()`, `_is_hotfix_branch()`
- 所有门禁检查支持新格式

### 正则表达式

```python
# 新格式
feature/123-user-login  → ^feature/(\d+)
hotfix/456-payment-fix  → ^hotfix/(\d+)

# 旧格式（兼容）
issue_123               → ^issue_(\d+)
hotfix_456              → ^hotfix_(\d+)
```
