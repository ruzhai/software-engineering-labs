"""顾客端补充界面：房型详情、评价提交。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from hotel.core.errors import NotFound
from hotel.core.money import format_cents
from hotel.m05_order.model import OrderStatus
from hotel.ui.app import Screen
from hotel.ui.common import guarded, make_table


class HotelDetailScreen(Screen):
    title = "房型详情"

    def build(self) -> None:
        item = self.app.selected_room_type
        if item is None:
            ttk.Label(self, text="请先查询并选择一个房型").pack(pady=20)
            return

        box = ttk.LabelFrame(self, text=f"{item.store_name} · {item.room_type_name}", padding=16)
        box.pack(fill="x", padx=16, pady=12)
        ttk.Label(
            box,
            text=(
                f"床型：{item.bed_type}    可住 {item.max_guests} 人    "
                f"房间 {item.total_rooms} 间（维修 {item.under_repair} 间）"
            ),
        ).pack(anchor="w")

        ttk.Label(self, text="未来七天房价", padding=6).pack(anchor="w", padx=16)
        tree = make_table(self, ("日期", "房价"))
        today = date.today()
        for offset in range(7):
            day = today + timedelta(days=offset)
            try:
                text = format_cents(
                    self.services.pricing.get_price(item.room_type_id, day).price_cents
                )
            except NotFound:
                text = "未设置"
            tree.insert("", "end", values=(day.isoformat(), text))

        actions = ttk.Frame(self)
        actions.pack(pady=8)
        ttk.Button(actions, text="返回结果", command=self.go_back).pack(side="left", padx=6)
        ttk.Button(actions, text="去下单", command=self.go_order).pack(side="left", padx=6)

    def go_back(self) -> None:
        from hotel.ui.customer import ResultScreen  # pylint: disable=import-outside-toplevel

        self.app.show(ResultScreen)

    def go_order(self) -> None:
        from hotel.ui.customer import OrderScreen  # pylint: disable=import-outside-toplevel

        self.app.show(OrderScreen)


class ReviewScreen(Screen):
    title = "提交评价"

    def build(self) -> None:
        ttk.Label(self, text="选择一笔已退房的订单", padding=8).pack(anchor="w", padx=8)
        self.tree = make_table(self, ("订单号", "入住", "离店", "金额"))
        self.orders: dict[str, object] = {}
        self.refresh()

        form = ttk.LabelFrame(self, text="评价内容", padding=12)
        form.pack(fill="x", padx=16, pady=6)
        self.score = tk.IntVar(value=5)
        self.content = tk.StringVar()
        ttk.Label(form, text="评分").grid(row=0, column=0, sticky="e", padx=6)
        ttk.Spinbox(form, from_=1, to=5, textvariable=self.score, width=5).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(form, text="内容").grid(row=0, column=2, sticky="e", padx=6)
        ttk.Entry(form, textvariable=self.content, width=48).grid(row=0, column=3)
        ttk.Button(form, text="提交评价", command=self.submit).grid(row=0, column=4, padx=8)

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
