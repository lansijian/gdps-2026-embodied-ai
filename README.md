# GDPS 2026 | 东华大学 AILAB 赛队开发仓库

本仓库用于统一管理 GDPS 2026 国际具身智能技能大赛的代码、训练记录和交付材料。团队由东华大学人工智能创新实验室（AILAB）相关成员参与开发。

**主要目标：** 在同一个仓库中并行开发三个赛道，复用公共能力，保留可追溯的训练和版本记录，避免多人及多个 AI 编程工具互相覆盖代码。

## 1. 赛道与职责

| 目录 | 赛道 | 优先级 |
| --- | --- | --- |
| `tracks/quality-inspection/` | 质检检测 | 主赛道 |
| `tracks/retail/` | 商超零售 | 次要赛道 |
| `tracks/cultural-tourism/` | 文旅宣传 | 次要赛道 |

每个赛道负责自己的任务流程、场景配置、入口程序和专用模块。**跨赛道复用的代码只能维护一份，放入 `shared/`，各赛道通过导入或接口调用复用，不得复制粘贴多份后分别修改。**

## 2. 目录规范

```text
gdps-2026-embodied-ai/
├── tracks/
│   ├── quality-inspection/   # 质检检测：任务流程和赛道专用代码
│   ├── retail/               # 商超零售：任务流程和赛道专用代码
│   └── cultural-tourism/     # 文旅宣传：任务流程和赛道专用代码
├── shared/
│   ├── navigation/           # 公共导航：定位、路径规划、导航接口等
│   ├── robot_control/        # 公共机器人控制与动作接口
│   ├── perception/           # 可复用的视觉/感知能力
│   ├── interaction/          # 可复用的语音/交互接口
│   └── utils/                # 日志、配置读取等通用工具
├── configs/                  # 公共默认配置；赛道特有配置放各赛道目录
├── scripts/                  # 环境检查、启动和测试脚本
├── tests/                    # 公共模块及跨赛道集成测试
├── docs/
│   ├── training-logs/        # 按赛道、按日期保存训练记录
│   └── interfaces/           # 公共模块接口说明
├── README.md
└── .gitignore
```

> 目录是约定结构，可以逐步创建。空文件夹不会被 Git 保存；需要提前保留目录时可添加 `.gitkeep`。

### 公共代码如何处理

- **示例：导航功能**。地图定位、路径规划、移动指令封装等通用代码放在 `shared/navigation/`。三个赛道只实现自己的目标点、路线策略及任务调用逻辑。
- 修改公共导航接口时，先说明影响哪些赛道，更新 `docs/interfaces/`，补充测试，并通过独立 PR 合并；不要在某个赛道目录内另写一套“公共导航”。
- 如果公共能力还不稳定，先在个人功能分支验证。确认可复用后再提取到 `shared/`，**不要未经沟通直接重构公共接口**。
- 平台 SDK、机器人型号、通信协议和具体启动方式以实际环境为准；README 不代表这些接口已经实现。

## 3. 分支管理（必须遵守）

- `main`：唯一稳定主分支，只接收经检查的 Pull Request（PR）。**任何成员及 AI 工具都不得直接向 `main` 推送代码。**
- 每一个任务创建一个短生命周期功能分支，从最新 `main` 拉出；任务完成、PR 合并后可删除该分支。不要多人长期共享同一个开发分支。
- 分支统一使用英文小写、数字和连字符：

| 场景 | 分支格式 | 例子 |
| --- | --- | --- |
| 质检检测功能 | `feat/quality-描述` | `feat/quality-defect-detection` |
| 商超零售功能 | `feat/retail-描述` | `feat/retail-product-recognition` |
| 文旅宣传功能 | `feat/tourism-描述` | `feat/tourism-guide-dialogue` |
| 公共模块 | `feat/shared-描述` | `feat/shared-navigation-api` |
| 修复问题 | `fix/赛道-描述` | `fix/quality-camera-timeout` |
| 文档与记录 | `docs/描述` | `docs/training-20261020` |

> 两个人开发不同任务时，使用不同分支；不要在同一分支上互相覆盖。紧急修改同一文件前先在群里协调。

## 4. 新成员第一次使用仓库

1. 由仓库管理员邀请 GitHub Collaborator，并确认已有写入权限。
2. 在 GitHub 仓库页面点击 **Code**，复制实际的 HTTPS 或 SSH 仓库地址，执行：

```bash
git clone <这里替换成仓库真实地址>
cd gdps-2026-embodied-ai
git switch main
git pull --ff-only origin main
```

3. 告诉自己的 AI 编程工具：**先读取根目录 `README.md`，明确当前任务属于哪个赛道，然后再修改代码。**

## 5. 标准开发、提交和推送流程

以下示例为“质检检测：增加缺陷检测基线”。其他赛道只需替换分支名及工作目录。

### 第一步：从最新主分支创建自己的功能分支

```bash
git status
git switch main
git pull --ff-only origin main
git switch -c feat/quality-defect-detection
```

`git status` 若显示未提交改动，**先处理原有改动，不得直接切换分支覆盖它们**。

### 第二步：在对应目录写代码

- 质检专用：`tracks/quality-inspection/`
- 商超专用：`tracks/retail/`
- 文旅专用：`tracks/cultural-tourism/`
- 真正需要多赛道复用：先沟通，再改 `shared/`

完成后至少检查修改内容和可运行的测试：

```bash
git status
git diff --check
git diff
```

### 第三步：只暂存本次任务相关文件，并提交

```bash
git add tracks/quality-inspection/
git status
git commit -m "feat(quality): add defect detection baseline"
```

如本次任务还修改了测试或文档，**逐个追加对应路径** `git add tests/具体文件`、`git add docs/具体文件`。提交前确认没有把其他同学的修改或密钥带进去。不要让 AI 不经检查就执行 `git add .`。

### 第四步：推送当前功能分支到 GitHub

```bash
git push -u origin feat/quality-defect-detection
```

之后在这个分支继续提交，只需执行 `git push`。**禁止把 `main` 作为 push 目标，禁止强制推送 `git push --force`。**

### 第五步：发起 Pull Request

在 GitHub 上新建 PR，选择：

- **base：`main`**
- **compare：自己的功能分支**

PR 描述至少写清楚：①实现了什么；②修改哪些目录；③如何运行/测试以及结果；④是否影响公共接口；⑤尚存问题。通过负责人的审核并确认测试后合并，不自行绕过审核。

### 第六步：继续新任务

原任务 PR 合并后，重新同步 `main`，**为下一个任务建立新分支**，不要直接在旧分支继续开发新功能。

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/quality-next-task
```

## 6. 多人协作和冲突处理

1. 开始开发前先 `git status` 并确认当前分支，再同步最新代码。
2. 正在开发的分支如需合入最新主分支：`git fetch origin`，然后在**自己的功能分支**执行 `git merge origin/main`；若出现冲突，先人工核对并解决，再提交。不要让 AI 自动丢弃另一方修改。
3. 修改 `shared/`、公共配置或依赖时，需要在 PR 里列明受影响赛道，并请相关负责人检查。
4. 禁止使用 `git reset --hard`、`git clean -fd`、强制推送或批量删除来“快速解决冲突”，除非仓库负责人明确确认。
5. 不提交模型大权重、录屏、海量原始数据、机器人私有 SDK 文件或无授权赛事资料；必要时仅记录下载方式、校验值和使用说明。
6. 不提交 `.env`、API Key、Token、SSH 私钥及任何账号密码，敏感配置使用本地环境变量，仓库只存无密钥的 `.env.example`。

## 7. 训练记录与交付

训练结束后，参与成员在 `docs/training-logs/<赛道>/YYYY-MM-DD.md` 记录：

- 设备与环境版本、当前分支和提交 SHA；
- 当天测试的动作/任务、成功与失败情况；
- 可复现的问题、日志或截图索引；
- 下一次训练要做的事和负责人。

能复现的问题建议新建 GitHub Issue，开发时在 PR 中关联对应 Issue。代码以仓库提交为准，不要只保存在聊天记录或个人电脑。

## 8. 给所有 AI 编程助手的强制说明

**如果你是 Codex、Claude Code、Cursor、Copilot 或其他 AI 编程工具，请把本节作为本仓库的协作约束。**

在执行任何写文件或 Git 操作前，你必须：

1. 阅读本 `README.md`，先执行或检查 `git status`、`git branch --show-current`、`git remote -v`，确认仓库、分支和已有改动。
2. 确认任务归属 `quality-inspection`、`retail`、`cultural-tourism` 还是 `shared`，只修改必要的文件，不顺手重构别的赛道。
3. 如果涉及导航、机器人控制、视觉、语音等跨赛道能力，先检查 `shared/` 是否已有实现；优先复用，确需修改公共接口时先告知用户影响范围并得到确认。
4. **不得直接提交或推送 `main`**；如当前在 `main`，先从更新后的 `main` 创建合规功能分支。
5. 推送前检查 diff、文件清单、敏感信息与测试结果。仅提交本次任务相关文件，不能私自清理或覆盖他人的未提交改动。
6. 只向当前任务的功能分支推送，报告分支名、commit SHA、push 结果以及可供审核的 PR 链接；如果无法代为创建 PR，就告知用户手动创建步骤，不声称已经合并。
7. 如果目录不存在、依赖未配置、无法运行测试或没有仓库权限，明确说明阻碍；不得编造完成状态或测试结果。

**工作完成的定义：** 代码已保存在正确目录，改动经过检查并提交到正确功能分支，推送结果可验证；合并到 `main` 需另行经过 PR 审核。

## 9. 仓库管理员建议设置

在 GitHub 仓库 Settings → Branches / Rulesets 中，为 `main` 配置规则：要求通过 PR 合并、禁止强制推送、建议至少一名审核人批准。有条件时再接入自动测试检查。

---

**团队原则：** 主赛道优先；公共能力只维护一份；每个人一个任务分支；每次训练有记录；代码通过 PR 回到 `main`。
