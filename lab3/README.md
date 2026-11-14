# 实验三：软件实现与构建

要求原件见 `实验三_软件实现与构建.pdf`。截止 2026-11-29 23:59，提交到 cslab-cms。

## 实现概况

按实验二的 UML 类图与 M1–M10 模块划分，用 Python 3.12 + SQLite + Tkinter 实现酒店预订管理系统。

- 生产代码约 4800 行（`code/src`，不含空行与注释），测试约 1400 行
- 24 个类各对应一张 SQLite 表；`src/hotel/m01_account` … `m10_notify` 与模块编号一一对应
- 状态机、库存扣减、并发抢房、改价互斥、权限范围都有对应测试
- 界面 10 屏：登录、房型查询、查询结果、下单确认、支付、我的订单、房态看板、办理入住、办理退房、改价与审批

## 运行

```bash
cd code
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m hotel.seed        # 重建数据库并写入演示数据
.venv/Scripts/python -m hotel.ui.app      # 启动界面
```

演示账号密码统一为 `secret1`：顾客 `13800000001`、前台 `13900000003`、店长 `13900000002`、片区负责人 `13900000001`。

## 测试与代码风格

```bash
.venv/Scripts/python -m pytest
.venv/Scripts/python -m black --check src tests
.venv/Scripts/python -m pylint src
```

## 交付

提交包结构：

```
实验3_241220031_曹继贤/
├── 实验报告.pdf
├── UML/          ← 本目录 UML/
└── code/         ← 本目录 code/（保留包结构，可直接运行）
```

实验报告由本人撰写，仓库内不保留报告草稿。实现过程中的取舍与 AI 使用记录见 `_过程材料/`。
