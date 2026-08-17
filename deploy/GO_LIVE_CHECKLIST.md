# Req2Code 上线前检查清单

## 1. 发布仓库

- [ ] 确定开源/内部授权方式并添加 `LICENSE`
- [ ] 确认 README 中英文内容同步
- [ ] 确认仓库中没有真实凭据、运行报告、状态文件或演示仓库
- [ ] GitHub Actions 的 Python 3.10、3.11、3.12 测试全部通过
- [ ] `python -m pip wheel . --no-deps --wheel-dir dist` 构建成功

## 2. 配置和凭据

- [ ] 从 `config.example.yaml` 或对应 `deploy/config.*.yaml` 创建环境专用配置
- [ ] 用 `REQ2CODE_CONFIG` 指向环境专用配置文件
- [ ] 替换所有 `REPLACE_ME_*` 占位值
- [ ] 核对 TAPD workspace 与字段映射
- [ ] 使用强随机 `review.callback_secret`
- [ ] 把 `review.ip_allowlist` 限制为真实审核入口 IP
- [ ] TAPD、Git 和通知凭据均采用最小权限

## 3. 开发引擎

- [ ] 明确默认 `engines.active`
- [ ] 至少一个 Claude Code、Codex 或 Cursor CLI 可执行并已认证
- [ ] `req2code doctor` 中 executable 和 authentication 都为 PASS
- [ ] 引擎超时和重试次数符合目标项目规模

## 4. 测试与质量门禁

- [ ] `testing.unit_command` 能在目标代码仓库中运行
- [ ] `testing.coverage_command` 会输出可解析的百分比
- [ ] 最低覆盖率适合目标项目
- [ ] 按需配置 Lint、安全扫描和 AI Review
- [ ] 完成 `docs/TESTING.zh-CN.md` 的 Mock 完整流程
- [ ] 检查首次运行生成完整六段项目记忆，第二次相同 SHA 不重复扫描
- [ ] 检查分支分叉或历史重写时自动完整重建而不是复用旧记忆
- [ ] 检查拒绝不会晋升候选记忆，批准推送后才晋升
- [ ] 检查 mirror 目录和项目记忆目录只允许运行账号访问

## 5. 审批与安全

- [ ] `review.approval_base_url` 指向真实审核服务
- [ ] 回调签名、时间戳、nonce 和重放防护联调通过
- [ ] 状态目录仅运行账号可读写，不由公共 Web 服务暴露
- [ ] Git 平台继续启用生产分支保护和审核规则
- [ ] 验证开发阶段 push URL 被阻断
- [ ] 验证拒绝不 commit/push，批准才 commit/push
- [ ] 验证报告后修改代码会使 run 进入 stale

## 6. 测试环境联调

- [ ] `req2code fetch` 和 `req2code show` 能读取 TAPD
- [ ] 单个需求/Bug、多个工作项共用分支都已验证
- [ ] 本地仓库和远程克隆两种模式都已验证
- [ ] 报告包含方案、文件列表、测试/覆盖率结果和推送目标
- [ ] 远程提交 SHA 与 Req2Code 记录一致

## 7. 服务部署

- Windows 示例：`deploy/install_windows_service.ps1`
- Linux systemd 示例：`deploy/install_linux_systemd.sh`
- [ ] 使用部署前审阅过的绝对路径和专用服务账号
- [ ] 服务启动后仅从允许的网络访问审批端口
- [ ] 配置日志轮转、状态目录备份和告警