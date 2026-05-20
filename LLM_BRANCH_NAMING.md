# LLM 分支命名功能使用说明

## 功能说明

ai-workflow 现在支持使用 LLM 自动将中文 Issue 标题转换为英文分支描述。

## 配置方法

在项目根目录的 `.env` 文件中添加：

```bash
# LLM 配置（可选，用于生成英文分支描述）
LLM_API_KEY=sk-xxx                              # 必需
LLM_BASE_URL=https://api.openai.com/v1         # 可选，默认 OpenAI
LLM_MODEL=gpt-4o-mini                           # 可选，默认 gpt-4o-mini
```

## 使用效果

### 配置 LLM 后

```bash
# Issue 标题：用户登录优化
ccg gitlab feature start 123
# 生成分支：feature/123-user-login-optimization

# Issue 标题：修复支付页面崩溃问题
ccg gitlab hotfix start 456
# 生成分支：hotfix/456-fix-payment-crash
```

### 未配置 LLM（回退到规则提取）

```bash
# Issue 标题：用户登录优化
ccg gitlab feature start 123
# 生成分支：feature/123  (纯中文无法提取，只有 ID)

# Issue 标题：User Login Optimization
ccg gitlab feature start 789
# 生成分支：feature/789-user-login-optimization  (提取英文部分)
```

## 技术细节

- **超时保护**：LLM 调用超时 15 秒后自动回退到规则提取
- **错误处理**：LLM 调用失败时自动回退，不影响分支创建流程
- **格式保证**：LLM 生成的 slug 会经过二次清理，确保只包含小写字母、数字、连字符
- **长度限制**：自动截断到 30 字符

## 兼容性

- 未配置 LLM 时，功能完全向后兼容，使用原有的规则提取逻辑
- 配置 LLM 后，对纯中文标题的处理效果显著提升
