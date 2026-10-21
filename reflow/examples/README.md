# 回流请求示例（S22）

三个示例分别对应三类上报。`_comment` 字段仅用于阅读，**发送前请删除**（平台不接受未定义字段）。

| 文件 | 接口 | 校验命令 |
| --- | --- | --- |
| `report-s22-final.json` | `POST /reflow/tasks/report` | `validate --kind report --file ...` |
| `trajectory-batch.json` | `POST /reflow/trajectories/batch` | `validate --kind trajectory --file ...` |
| `embodied-batch.json` | `POST /reflow/embodied/batch` | `validate --kind embodied --file ...` |

校验会加载 `reflow/s22_spec.json`，检查检查点 ID、record_kind、状态是否属于任务包允许值。
示例中的 evaluation_id/session_id/时间/坐标/关节值均为占位，**必须替换为真实数据**；无位姿不要上传轨迹。
