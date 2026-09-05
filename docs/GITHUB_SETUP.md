# GitHub连接与接管

本仓库已经发布为私有仓库 `Kato814/EV-Charging-Forecasting-Research`，并已实际采用Issue、分支、PR和CI工作流。早期“从ZIP首次Publish”“连接仅支持读取”的说明已过时，从当前操作说明中移除；不需要重新创建仓库或重新上传历史压缩包。

新主控先读取 [CURRENT_STATUS](../CURRENT_STATUS.md)、[HANDOFF](../HANDOFF.md)，再通过本会话可用的GitHub连接读取活动PR/Issue。连接权限可能随会话变化，实际调用成功才算完成，不能凭旧对话声称拥有权限或已写入。

本地Codex继续使用已有独立worktree。只在任务进程结束且状态清晰时同步远端，不移动/覆盖用户原main工作区，不改变原remote，不force push。

需要新环境检出时，使用已认证Git或GitHub Desktop克隆现有私有仓库；凭据保存在本机的凭据机制，不放入URL、对话、脚本或提交。raw数据不随Git克隆产生，应从本地已核验数据目录定位，不据此重新下载。

执行、数据保全和PR验收见 [WORKFLOW.md](WORKFLOW.md)。仓库可见性、权限、分支保护、runner设置均不因本次整理而变更。
