"""顾客端补充界面：房型详情、评价提交。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from hotel.core.errors import NotFound
from hotel.core.money import format_cents
from hotel.m05_order.model import OrderStatus
from hotel.ui import theme
from hotel.ui.app import Screen
from hotel.ui.common import guarded


class HotelDetailScreen(Screen):
    title = "房型详情"
    subtitle = "查看房型基本信息与近期房价"

    def build(self) -> None:
        item = self.app.selected_room_type
        if item is None:
            theme.badge(self, "请先查询并选择一个房型", "warning").pack(anchor="w")
            return

        theme.kpi_row(
            self,
            [
                ("门店", item.store_name, item.city, theme.TEXT),
                ("房型", item.room_type_name, item.bed_type, theme.TEXT),
                ("可住人数", f"{item.max_guests} 人", "含成人与儿童", theme.TEXT),
                (
                    "房间总数",
                    str(item.total_rooms),
                    f"维修中 {item.under_repair} 间",
                    theme.WARNING,
                ),
            ],
        )

        body = theme.card(self, "未来七天房价", fill="both", expand=True)
        tree = theme.table(body, ("日期", "星期", "房价"), widths=[160, 120, 160], height=8)
        weekdays = "一二三四五六日"
        today = date.today()
        for offset in range(7):
            day = today + timedelta(days=offset)
            try:
                text = format_cents(
                    self.services.pricing.get_price(item.room_type_id, day).price_cents
                )
            except NotFound:
                text = "未设置"
            tree.insert("", "end", values=(day.isoformat(), f"周{weekdays[day.weekday()]}", text))

        actions_row = theme.actions(body)
        theme.primary(actions_row, "去下单", self.go_order).pack(side="right")
        theme.ghost(actions_row, "返回结果", self.go_back).pack(side="right", padx=(0, 10))

    def go_back(self) -> None:
        from hotel.ui.customer import ResultScreen  # pylint: disable=import-outside-toplevel

        self.app.show(ResultScreen)

    def go_order(self) -> None:
        from hotel.ui.customer import OrderScreen  # pylint: disable=import-outside-toplevel

        self.app.show(OrderScreen)


class ReviewScreen(Screen):
    title = "提交评价"
    subtitle = "已退房的订单可以评价一次"

    def build(self) -> None:
        body = theme.card(self, "可评价的订单", fill="both", expand=True)
        self.tree = theme.table(
            body,
            ("订单号", "门店", "入住", "离店", "金额"),
            widths=[190, 130, 110, 110, 110],
            height=12,
        )

        form = theme.card(self, "评价内容", fill="x", pady=(14, 0))
        line = tk.Frame(form, bg=theme.SURFACE)
        line.pack(fill="x")
        self.score = tk.IntVar(value=5)
        self.content = tk.StringVar()
        theme.field_label(line, "评分").pack(side="left", padx=(0, 8))
        ttk.Spinbox(
            line, from_=1, to=5, textvariable=self.score, width=5, style="App.TSpinbox"
        ).pack(side="left", padx=(0, 18))
        theme.field_label(line, "内容").pack(side="left", padx=(0, 8))
        theme.entry(line, self.content, 48).pack(side="left")

        actions_row = theme.actions(form)
        theme.primary(actions_row, "提交评价", self.submit).pack(side="right")

        self.orders: dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.orders.clear()
        for order in self.services.order.list_my_orders(self.app.session):
            if order.status is not OrderStatus.CHECKED_OUT:
                continue
            row = self.tree.insert(
                "",
                "end",
                values=(
                    order.order_no,
                    order.store_name,
                    order.check_in_date,
                    order.check_out_date,
                    format_cents(order.total_cents),
                ),
            )
            self.orders[row] = order

    @guarded
    def submit(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一笔订单")
            return
        order = self.orders[selection[0]]
        self.services.performance.submit_review(
            self.app.session,
            order_id=order.id,
            score=self.score.get(),
            content=self.content.get(),
        )
        messagebox.showinfo("评价成功", "感谢反馈")
        self.refresh()
