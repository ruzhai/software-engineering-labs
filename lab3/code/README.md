# 酒店预订管理系统（实验三实现）

按实验二的 UML 类图与 M1–M10 模块划分实现。Python 3.12 + SQLite + Tkinter。

## 安装与运行

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m hotel.seed      # 建库并写入演示数据
.venv/Scripts/python -m hotel.ui.app    # 启动界面
```

## 测试与风格

```bash
.venv/Scripts/python -m pytest
.venv/Scripts/python -m pytest --cov   # 如需覆盖率
.venv/Scripts/python -m black src tests
.venv/Scripts/python -m pylint src
```

## 目录

- `src/hotel/core/`：错误类型、时钟、金额、数据库访问
- `src/hotel/m01_account/` … `m10_notify/`：M1–M10 各模块，每个包含 model / repository / service
- `src/hotel/ui/`：Tkinter 界面
- `tests/`：service 层测试，背后接真实 SQLite
