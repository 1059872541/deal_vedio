# -*- coding: utf-8 -*-
"""vedio.stages —— 每个能力一个模块，对外只暴露一个函数。

共同约定（**这是"能力"和"脚本"的分界线**）：

1. 只收 ``(project, ...)``，不收路径 —— 路径一律由 ``vedio.context`` 推导
2. 幂等：重复跑结果一致，或者明确报"已完成"
3. 抛 ``ContextError`` 或自带异常，不 ``sys.exit``
4. 不 print 进度给人看 —— 那是 CLI 的事；需要留痕就写 ``events.jsonl``
"""
