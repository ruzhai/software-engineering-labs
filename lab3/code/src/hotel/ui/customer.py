"""顾客端：查询、结果、下单、支付、我的订单。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, simpledialog, ttk

from hotel.core.errors import NotFound
from hotel.core.money import format_cents
from hotel.m05_order.model import OrderStatus
from hotel.m05_order.service import RoomRequest
from hotel.ui import theme
from hotel.ui.app import Screen
from hotel.ui.common import ORDER_STATUS_LABEL, guarded, parse_date


class QueryScreen(Screen):
    title = "房型查询"
    subtitle = "按城市、入住日期与人数筛选在售房型"

    def build(self) -> None:
        body = theme.card(self, "查询条件", fill="x", pady=(0, 14))

        today = date.today()
        self.city = tk.StringVar(value="南京")
        self.check_in = tk.StringVar(value=today.isoformat())
        self.check_out = tk.StringVar(value=(today + timedelta(days=1)).isoformat())
        self.guests = tk.StringVar(value="2")

        row = tk.Frame(body, bg=theme.SURFACE)
        row.pack(fill="x")
        for label, variable, width in (
            ("城市", self.city, 10),
            ("入住日期", self.check_in, 14),
            ("离店日期", self.check_out, 14),
            ("人数", self.guests, 6),
        ):
            box = tk.Frame(row, bg=theme.SURFACE)
            box.pack(side="left", padx=(0, 18))
            theme.field_label(box, label).pack(anchor="w")
            theme.entry(box, variable, width).pack(anchor="w", pady=(4, 0))

        actions_row = theme.actions(body, pady=(16, 0))
        theme.primary(actions_row, "查询", self.search).pack(side="right")

        hot = theme.card(self, "热门房型", fill="both", expand=True)
        tree = theme.table(
            hot,
            ("门店", "房型", "床型", "可住人数", "今晚房价"),
            widths=[140, 150, 100, 110, 130],
            height=8,
        )
        for item in self.services.store.list_room_types(self.city.get(), 2):
            try:
                price = format_cents(
                    self.services.pricing.get_price(item.room_type_id, today).price_cents
                )
            except NotFound:
                price = "未设置"
            tree.insert(
                "",
                "end",
                values=(
                    item.store_name,
                    item.room_type_name,
                    item.bed_type,
                    item.max_guests,
                    price,
                ),
            )

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
    subtitle = "选择房型查看详情或直接下单"

    def build(self) -> None:
        body = theme.card(self, "可选房型", fill="both", expand=True)
        self.tree = theme.table(
            body,
            ("门店", "房型", "床型", "可住人数", "房间数", "维修中", "可售"),
            widths=[130, 130, 90, 90, 90, 90, 90],
            height=14,
        )
        actions_row = theme.actions(body)
        theme.primary(actions_row, "下一步：确认订单", self.choose).pack(side="right")
        theme.ghost(actions_row, "查看详情", self.detail).pack(side="right", padx=(0, 10))

        self.rows: dict[str, object] = {}
        self.load(self.app.search_results)

    def load(self, results) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        check_in = self.app.search_params.get("check_in")
        for item in results:
            remaining = "—"
            if check_in is not None:
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
            theme.badge(self.tree.master, "没有符合条件的房型，请调整查询条件", "warning").pack(
                anchor="w", pady=(10, 0)
            )

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个房型")
            return None
        return self.rows[selection[0]]

    @guarded
    def choose(self) -> None:
        item = self._selected()
        if item is None:
            return
        self.app.selected_room_type = item
        self.app.show(OrderScreen)

    @guarded
    def detail(self) -> None:
        item = self._selected()
        if item is None:
            return
        self.app.selected_room_type = item
        from hotel.ui.customer_extra import (  # pylint: disable=import-outside-toplevel
            HotelDetailScreen,
        )

        self.app.show(HotelDetailScreen)


class OrderScreen(Screen):
    title = "确认订单"
    subtitle = "核对房型、日期与金额后提交"

    def build(self) -> None:
        room_type = self.app.selected_room_type
        params = self.app.search_params
        body = theme.card(self, "订单信息", fill="x", pady=(0, 14))

        grid = tk.Frame(body, bg=theme.SURFACE)
        grid.pack(fill="x")
        for index, (label, value) in enumerate(
            (
                ("门店", room_type.store_name),
                ("房型", room_type.room_type_name),
                ("入住", str(params["check_in"])),
                ("离店", str(params["check_out"])),
            )
        ):
            column = index * 2
            theme.field_label(grid, label).grid(row=0, column=column, sticky="e", padx=(0, 8))
            tk.Label(grid, text=value, bg=theme.SURFACE, fg=theme.TEXT, font=theme.FONT_BODY).grid(
                row=0, column=column + 1, sticky="w", padx=(0, 28)
            )

        self.nights = (params["check_out"] - params["check_in"]).days
        self.qty = tk.IntVar(value=1)
        theme.field_label(grid, "间数").grid(row=1, column=0, sticky="e", pady=(14, 0))
        ttk.Spinbox(grid, from_=1, to=5, textvariable=self.qty, width=5, style="App.TSpinbox").grid(
            row=1, column=1, sticky="w", pady=(14, 0)
        )

        self.summary = tk.Frame(body, bg=theme.SURFACE_ALT)
        self.summary.pack(fill="x", pady=(16, 0))
        self.summary_label = tk.Label(
            self.summary,
            text="",
            bg=theme.SURFACE_ALT,
            fg=theme.TEXT,
            font=theme.FONT_BODY,
            justify="left",
            anchor="w",
            padx=14,
            pady=12,
        )
        self.summary_label.pack(fill="x")
        self.refresh_total()

        actions_row = theme.actions(body)
        theme.primary(actions_row, "提交订单", self.submit).pack(side="right")

    def refresh_total(self) -> None:
        params = self.app.search_params
        room_type = self.app.selected_room_type
        total = 0
        detail = []
        try:
            for offset in range(self.nights):
                night = date.fromordinal(params["check_in"].toordinal() + offset)
                price = self.services.pricing.get_price(room_type.room_type_id, night)
                total += price.price_cents
                detail.append(f"{night}  {format_cents(price.price_cents)}")
        except NotFound:
            self.summary_label.configure(text="所选日期尚未设置房价")
            return
        nights_text = "    ".join(detail)
        self.summary_label.configure(
            text=f"共 {self.nights} 晚\n{nights_text}\n合计 {format_cents(total)}"
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
    subtitle = "支付成功后订单转为已确认"

    def build(self) -> None:
        order = self.app.current_order
        holder = tk.Frame(self, bg=theme.BG)
        holder.place(relx=0.5, rely=0.4, anchor="center")

        box = tk.Frame(
            holder, bg=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1
        )
        box.pack()
        inner = tk.Frame(box, bg=theme.SURFACE)
        inner.pack(padx=48, pady=36)

        tk.Label(
            inner, text="待支付", bg=theme.SURFACE, fg=theme.MUTED, font=theme.FONT_SMALL
        ).pack(anchor="w")
        tk.Label(
            inner,
            text=format_cents(order.total_cents),
            bg=theme.SURFACE,
            fg=theme.ACCENT,
            font=(theme.FAMILY, 28, "bold"),
        ).pack(anchor="w", pady=(4, 6))
        tk.Label(
            inner,
            text=f"订单号 {order.order_no}",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
        ).pack(anchor="w", pady=(0, 22))

        theme.primary(inner, "确认支付", self.pay).pack(fill="x")

    @guarded
    def pay(self) -> None:
        order = self.app.current_order
        payment = self.services.payment.create_payment(self.app.session, order.id)
        self.services.payment.pay(payment.pay_no)
        messagebox.showinfo("支付成功", f"订单 {order.order_no} 已确认")
        self.app.show(CustomerOrdersScreen)


class CustomerOrdersScreen(Screen):
    title = "我的订单"
    subtitle = "查看订单状态，进行支付、取消或评价"

    def build(self) -> None:
        body = theme.card(self, "订单列表", fill="both", expand=True)
        self.tree = theme.table(
            body,
            ("订单号", "门店", "状态", "入住", "离店", "金额"),
            widths=[190, 120, 90, 110, 110, 110],
            height=14,
        )
        actions_row = theme.actions(body)
        theme.primary(actions_row, "去支付", self.go_pay).pack(side="right")
        theme.ghost(actions_row, "提交评价", self.review).pack(side="right", padx=(0, 10))
        theme.ghost(actions_row, "取消订单", self.cancel).pack(side="right", padx=(0, 10))
        theme.ghost(actions_row, "刷新", self.refresh).pack(side="left")

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
