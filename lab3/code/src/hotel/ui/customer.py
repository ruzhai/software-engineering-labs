"""顾客端：查询、结果、下单、支付、我的订单。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, simpledialog, ttk

from hotel.core.errors import NotFound
from hotel.core.money import format_cents
from hotel.m05_order.model import OrderStatus
from hotel.m05_order.service import RoomRequest
from hotel.ui.app import Screen
from hotel.ui.common import ORDER_STATUS_LABEL, guarded, parse_date


class QueryScreen(Screen):
    title = "查询房型"

    def build(self) -> None:
        box = ttk.LabelFrame(self, text="查询条件", padding=16)
        box.pack(fill="x", padx=16, pady=12)

        today = date.today()
        self.city = tk.StringVar(value="南京")
        self.check_in = tk.StringVar(value=today.isoformat())
        self.check_out = tk.StringVar(value=(today + timedelta(days=1)).isoformat())
        self.guests = tk.StringVar(value="2")

        for index, (label, variable, width) in enumerate(
            (
                ("城市", self.city, 12),
                ("入住日期", self.check_in, 14),
                ("离店日期", self.check_out, 14),
                ("人数", self.guests, 6),
            )
        ):
            ttk.Label(box, text=label).grid(row=0, column=index * 2, padx=6, sticky="e")
            ttk.Entry(box, textvariable=variable, width=width).grid(
                row=0, column=index * 2 + 1, padx=6
            )

        ttk.Button(box, text="查询", command=self.search).grid(row=0, column=8, padx=12)

    @guarded
    def search(self) -> None:
        check_in = parse_date(self.check_in.get(), "check_in")
        check_out = parse_date(self.check_out.get(), "check_out")
        guests = int(self.guests.get())
        results = self.services.store.list_room_types(self.city.get(), guests)
        self.app.search_params = {
            "check_in": check_in,
            "check_out": check_out,
            "guests": guests,
        }
        self.app.search_results = results
        self.app.show(ResultScreen)


class ResultScreen(Screen):
    title = "查询结果"

    def build(self) -> None:
        ttk.Label(self, text="选择房型后进入下单", padding=8).pack(anchor="w", padx=8)
        columns = ("门店", "房型", "床型", "可住人数", "房间数", "维修中", "可售")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=14)
        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=125, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=12, pady=6)
        self.rows: dict[str, object] = {}
        actions = ttk.Frame(self)
        actions.pack(pady=10)
        ttk.Button(actions, text="查看详情", command=self.detail).pack(side="left", padx=6)
        ttk.Button(actions, text="下一步：确认订单", command=self.choose).pack(side="left", padx=6)
        self.load(self.app.search_results)

    def load(self, results) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        check_in = self.app.search_params.get("check_in")
        for item in results:
            remaining = "—"
            if check_in is not None:
                # REQ-002 要求展示剩余数量，取入住当晚的线上剩余可售。
                remaining = self.services.inventory.query(
                    item.room_type_id, check_in
                ).online_remaining
            row_id = self.tree.insert(
                "",
                "end",
                values=(
                    item.store_name,
                    item.room_type_name,
                    item.bed_type,
                    item.max_guests,
                    item.total_rooms,
                    item.under_repair,
                    remaining,
                ),
            )
            self.rows[row_id] = item
        if not results:
            ttk.Label(self, text="没有符合条件的房型，请调整条件", foreground="#b45309").pack()

    @guarded
    def choose(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个房型")
            return
        self.app.selected_room_type = self.rows[selection[0]]
        self.app.show(OrderScreen)

    @guarded
    def detail(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个房型")
            return
        self.app.selected_room_type = self.rows[selection[0]]
        from hotel.ui.customer_extra import (  # pylint: disable=import-outside-toplevel
            HotelDetailScreen,
        )

        self.app.show(HotelDetailScreen)


class OrderScreen(Screen):
    title = "确认订单"

    def build(self) -> None:
        room_type = self.app.selected_room_type
        params = self.app.search_params
        box = ttk.LabelFrame(self, text="订单信息", padding=16)
        box.pack(fill="x", padx=16, pady=12)

        ttk.Label(box, text=f"门店：{room_type.store_name}").grid(row=0, column=0, sticky="w")
        ttk.Label(box, text=f"房型：{room_type.room_type_name}").grid(row=1, column=0, sticky="w")
        ttk.Label(box, text=f"{params['check_in']} 至 {params['check_out']}").grid(
            row=2, column=0, sticky="w"
        )

        self.qty = tk.IntVar(value=1)
        ttk.Label(box, text="间数").grid(row=3, column=0, sticky="w")
        ttk.Spinbox(box, from_=1, to=5, textvariable=self.qty, width=6).grid(
            row=3, column=1, sticky="w"
        )

        self.nights = (params["check_out"] - params["check_in"]).days
        self.summary = ttk.Label(box, text="")
        self.summary.grid(row=4, column=0, columnspan=2, pady=10, sticky="w")
        self.refresh_total()

        ttk.Button(self, text="提交订单", command=self.submit).pack(pady=8)

    def refresh_total(self) -> None:
        params = self.app.search_params
        room_type = self.app.selected_room_type
        nights = (params["check_out"] - params["check_in"]).days
        total = 0
        detail = []
        try:
            for offset in range(nights):
                night = date.fromordinal(params["check_in"].toordinal() + offset)
                price = self.services.pricing.get_price(room_type.room_type_id, night)
                total += price.price_cents
                detail.append(f"{night} {format_cents(price.price_cents)}")
        except NotFound:
            self.summary.configure(text="所选日期尚未设置房价")
            return
        self.nights = nights
        self.summary.configure(
            text=f"共 {nights} 晚：\n" + "\n".join(detail) + f"\n合计 {format_cents(total)}"
        )

    @guarded
    def submit(self) -> None:
        params = self.app.search_params
        room_type = self.app.selected_room_type
        order = self.services.order.create_order(
            self.app.session,
            store_id=room_type.store_id,
            request_no=_request_no(),
            items=[RoomRequest(room_type.room_type_id, self.qty.get())],
            check_in=params["check_in"],
            check_out=params["check_out"],
        )
        self.app.current_order = order
        self.app.show(PaymentScreen)


class PaymentScreen(Screen):
    title = "支付"

    def build(self) -> None:
        order = self.app.current_order
        box = ttk.LabelFrame(self, text="待支付", padding=20)
        box.pack(fill="x", padx=16, pady=16)
        ttk.Label(box, text=f"订单号：{order.order_no}").pack(anchor="w")
        ttk.Label(box, text=f"金额：{format_cents(order.total_cents)}").pack(anchor="w")
        ttk.Label(box, text="支付后订单转为已确认").pack(anchor="w", pady=6)
        ttk.Button(self, text="模拟支付成功", command=self.pay).pack(pady=10)

    @guarded
    def pay(self) -> None:
        order = self.app.current_order
        payment = self.services.payment.create_payment(self.app.session, order.id)
        self.services.payment.pay(payment.pay_no)
        messagebox.showinfo("支付成功", f"订单 {order.order_no} 已确认")
        self.app.show(CustomerOrdersScreen)


class CustomerOrdersScreen(Screen):
    title = "我的订单"

    def build(self) -> None:
        columns = ("订单号", "门店", "状态", "入住", "离店", "金额")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=14)
        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=150, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=12, pady=8)

        actions = ttk.Frame(self)
        actions.pack(pady=8)
        ttk.Button(actions, text="刷新", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(actions, text="去支付", command=self.go_pay).pack(side="left", padx=4)
        ttk.Button(actions, text="取消订单", command=self.cancel).pack(side="left", padx=4)
        ttk.Button(actions, text="提交评价", command=self.review).pack(side="left", padx=4)

        self.orders: dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.orders.clear()
        for order in self.services.order.list_my_orders(self.app.session):
            row = self.tree.insert(
                "",
                "end",
                values=(
                    order.order_no,
                    order.store_name,
                    ORDER_STATUS_LABEL.get(order.status.value, order.status.value),
                    order.check_in_date,
                    order.check_out_date,
                    format_cents(order.total_cents),
                ),
            )
            self.orders[row] = order

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一笔订单")
            return None
        return self.orders[selection[0]]

    @guarded
    def go_pay(self) -> None:
        order = self._selected()
        if order is None:
            return
        if order.status is not OrderStatus.PENDING_PAYMENT:
            messagebox.showinfo("提示", "该订单不需要支付")
            return
        self.app.current_order = order
        self.app.show(PaymentScreen)

    @guarded
    def cancel(self) -> None:
        order = self._selected()
        if order is None:
            return
        reason = simpledialog.askstring("取消订单", "请填写取消原因", initialvalue="行程有变")
        if reason is None:
            return
        self.services.order.cancel_order(self.app.session, order.id, reason)
        self.refresh()

    @guarded
    def review(self) -> None:
        order = self._selected()
        if order is None:
            return
        score = simpledialog.askinteger("评价", "评分（1-5）", minvalue=1, maxvalue=5)
        if score is None:
            return
        content = simpledialog.askstring("评价", "评价内容")
        if content is None:
            return
        self.services.performance.submit_review(
            self.app.session, order_id=order.id, score=score, content=content
        )
        messagebox.showinfo("评价成功", "感谢反馈")


def _request_no() -> str:
    from hotel.core.ids import new_id  # pylint: disable=import-outside-toplevel

    return new_id("req")
