# 多数据集小组协作回放

该工程是统一的多数据集版本。页面顶部可以在“旧数据集、数据集 A、数据集 B、数据集 C、数据集 D”之间切换，再选择该数据集中的小组。旧数据与四份新数据共用一个本地服务、一个回放页面和一个事后分析页面，不需要分别启动两个端口相同的程序。

四份新数据只共享采集结构，系统不会假定它们属于同一个实验。回放和事后分析始终保留 `datasetId`，同名 `group_id` 不会跨数据集合并。

## 新数据支持

- 统一回放代码、共享笔记、编辑器文本光标、页面操作、连接状态和任务完成记录；
- 房间聊天、共享 AI、私有 AI、私有 AI 转发使用独立频道；
- 私有 AI 可按成员筛选，AI 回复继续使用粉红色；
- 代码和笔记继续按最后编辑者着色，拖动时间轴后恢复对应时刻的完整状态；
- 新数据的事后分析只展示真实行为汇总、终稿归属和原始 AI 问答配对，不虚构 ICAP、异常或内容分析；
- 旧数据集继续保留已有的完整事后自动分析，并与四份新数据一起显示在数据集选择器中。

基于 `prodai_local_20260924` 的真实CSV记录，按小组统一时间轴回放三名成员共同维护的共享代码、共享笔记、房间聊天/AI、编辑器文本光标、页面操作、连接状态和任务完成记录。

## 页面包含

- 共享代码完整快照、变化行、当前操作者和每名成员最后记录的文本光标；
- 当前时间点的 Vega-Lite 代码实时生成可视结果；JSON 未完成或规范错误时显示当时的真实错误状态，不沿用后续图表；
- 实时可视结果可一键扩展到代码右侧的其余工作区；代码始终保留，图表按实际 SVG 尺寸智能适配，并支持鼠标滚轮连续缩放；
- 代码行、笔记段落及笔记图片按最后编辑者着色；后续覆盖会更新归属；
- 共享笔记文本与去重后的原始图片；
- 普通房间聊天、AI问题、AI回复及消息内代码；
- 结果页、数据、PDF、发送、提及、上传和完成等真实按钮操作；
- 三名成员稳定一致的颜色，贯穿内容背景、消息、活动和时间轴；
- 独立事后分析页面中的后期ICAP、协作异常、AI交互和笔记分析。

顶部“事后分析”可进入独立教师面板，当前包括：

- 成员行为参与和最终代码/笔记归属；
- ICAP窗口随时间变化及窗口详情；
- 协作异常提示的类型聚合与原始窗口跳转；
- 去重后的AI交互类型、Bloom层级、AI角色和小组后续反应；
- 代码演化里程碑、笔记见解和全部小组概览。

事后分析使用 `comprehensive_analysis_results.csv`、`analysis_results.csv`、`ai_chat_analysis.csv`、`sampled_notes_analysis.csv` 和 `note_analysis_results.csv`。自动分析只用于筛查，页面会持续显示数据兼容性和解释边界。

数据没有终端命令、stdout/stderr、测试用例结果、鼠标屏幕坐标、页面可见性或消息已读记录。`cursorpositions` 是编辑器文本光标；`online/offline` 是连接状态。界面不会用这些字段推断未采集的行为。

实时可视结果使用项目内置的 Vega、Vega-Lite 和 Vega-Embed 渲染。学生代码引用的 `ds_salaries.csv` 已作为只读任务数据放在项目根目录；该文件对应学生聊天中分享的 [YuluDuan/Hypothesis-Testing-Data-Science-salary-comparison-in-different-location](https://github.com/YuluDuan/Hypothesis-Testing-Data-Science-salary-comparison-in-different-location/blob/main/ds_salaries.csv)，共607条记录。回放仅把代码中的同名数据地址映射到这一本地副本，不修改学生的图形规范。

行级归属由连续完整快照做差分恢复。AI粉色只用于先前AI回复中存在足够长逐字匹配、且随后以批量新增方式进入代码或笔记的行；这表示可验证的文本来源匹配，不表示AI直接控制过编辑器。

## 运行

双击 `start.bat`，或执行：

```powershell
cd C:\Users\Admin\Desktop\4_data_student_program_replay
python server.py
```

打开 `http://127.0.0.1:8765/`。

## 重新生成组级数据

```powershell
python build_data.py
```

重新生成四份新数据：

```powershell
python build_collaborative_data.py
```

脚本默认读取桌面上的：

- `collaborative_cond_a_events.csv`
- `collaborative_cond_b_events.csv`
- `collaborative_cond_c_events.csv`
- `collaborative_cond_d_events.csv`

生成结果位于 `data/datasets/`，浏览器按数据集和小组分片加载，不会一次读取四份大型 CSV。

四份新数据中的可解析 Vega-Lite 代码主要引用 `/results.csv`。工程根目录已放入与字段完全匹配的原始任务数据（49,505 条国际足球比赛记录，包含 `home_score`、`away_score`、`tournament` 等字段），因此学生当时已经完成的图表可以在对应代码快照时刻真实渲染；代码尚未形成合法 JSON 时仍显示当时的真实编辑中状态。

生成结果位于 `data/groups/`。笔记中的Base64图片按内容哈希去重后保存在 `data/assets/`，避免在每个完整笔记快照中重复保存同一图片。

## 浏览器验证

测试需要本机Playwright运行库：

```powershell
$env:NODE_PATH='C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
node tests\smoke.cjs
```
