"""顾客端：按「选城市 → 搜日期 → 看门店房型 → 下单支付」的订房流程组织。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, simpledialog, ttk

from hotel.core.errors import NotFound, ValidationError
from hotel.core.money import format_cents
from hotel.m05_order.model import OrderStatus
from hotel.m05_order.service import RoomRequest
from hotel.ui import theme
from hotel.ui.app import Screen
from hotel.ui.common import ORDER_STATUS_LABEL, guarded, parse_date

CITIES = ("南京", "杭州", "上海")
WEEKDAYS = "一二三四五六日"


def _remaining_badge(parent, remaining: int) -> tk.Label:
    if remaining <= 0:
        return theme.badge(parent, "今日满房", "danger")
    if remaining <= 2:
        return theme.badge(parent, f"仅剩 {remaining} 间", "warning")
    return theme.badge(parent, f"有房 {remaining} 间", "success")


def _room_card(
    parent,
    item,
    *,
    remaining: int,
    price_cents: int | None,
    on_detail,
    on_book,
    show_store: bool = True,
) -> tk.Frame:
    """一张房型卡片：左侧门店与房型，中间价格，右侧操作。"""
    box = tk.Frame(parent, bg=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
    box.pack(fill="x", pady=(0, 10))

    left = tk.Frame(box, bg=theme.SURFACE)
    left.pack(side="left", fill="both", expand=True, padx=18, pady=14)

    tk.Label(
        left,
        text=item.room_type_name,
        bg=theme.SURFACE,
        fg=theme.TEXT,
        font=(theme.FAMILY, 12, "bold"),
        anchor="w",
    ).pack(fill="x")
    place = f"{item.store_name} · " if show_store else ""
    tk.Label(
        left,
        text=f"{place}{item.city}{item.district} · {item.bed_type} · 可住 {item.max_guests} 人",
        bg=theme.SURFACE,
        fg=theme.MUTED,
        font=theme.FONT_SMALL,
        anchor="w",
    ).pack(fill="x", pady=(4, 8))
    _remaining_badge(left, remaining).pack(anchor="w")

    middle = tk.Frame(box, bg=theme.SURFACE)
    middle.pack(side="left", padx=18)
    if price_cents is None:
        price_text, unit = "未定价", ""
    else:
        price_text, unit = format_cents(price_cents), " 起/晚"
    tk.Label(
        middle,
        text=price_text,
        bg=theme.SURFACE,
        fg=theme.DANGER,
        font=(theme.FAMILY, 16, "bold"),
    ).pack(anchor="e")
    tk.Label(middle, text=unit, bg=theme.SURFACE, fg=theme.MUTED, font=theme.FONT_SMALL).pack(
        anchor="e"
    )

    right = tk.Frame(box, bg=theme.SURFACE)
    right.pack(side="right", padx=18)
    theme.primary(right, "立即预订", on_book).pack(fill="x")
    theme.ghost(right, "查看详情", on_detail).pack(fill="x", pady=(6, 0))
    return box


class QueryScreen(Screen):
    title = "找酒店"
    subtitle = "选择城市与日期，查看在售房型"

    def build(self) -> None:
        today = date.today()
        self.city = tk.StringVar(value="南京")
        self.check_in = tk.StringVar(value=today.isoformat())
        self.check_out = tk.StringVar(value=(today + timedelta(days=2)).isoformat())
        self.guests = tk.StringVar(value="2")

        top = tk.Frame(self, bg=theme.BG)
        top.pack(fill="x", pady=(0, 10))
        tk.Label(top, text="当前城市", bg=theme.BG, fg=theme.MUTED, font=theme.FONT_SMALL).pack(
            side="left", padx=(2, 8)
        )
        ttk.Combobox(
            top,
            textvariable=self.city,
            values=list(CITIES),
            state="readonly",
            width=8,
            style="App.TCombobox",
        ).pack(side="left")
        for city in CITIES:
            tk.Button(
                top,
                text=city,
                bd=0,
                relief="flat",
                padx=10,
                pady=3,
                bg=theme.ACCENT_SOFT,
                fg=theme.ACCENT,
                activebackground=theme.ACCENT,
                activeforeground="#FFFFFF",
                font=theme.FONT_SMALL,
                cursor="hand2",
                command=lambda city=city: self.pick_city(city),
            ).pack(side="left", padx=(10, 0))

        search = theme.card(self, "预订", fill="x", pady=(0, 14))
        row = tk.Frame(search, bg=theme.SURFACE)
        row.pack(fill="x")
        for label, variable, width in (
            ("入住日期", self.check_in, 14),
            ("离店日期", self.check_out, 14),
            ("人数", self.guests, 6),
        ):
            field = tk.Frame(row, bg=theme.SURFACE)
            field.pack(side="left", padx=(0, 20))
            theme.field_label(field, label).pack(anchor="w")
            theme.entry(field, variable, width).pack(anchor="w", pady=(4, 0))
        theme.primary(row, "搜索酒店", self.search).pack(side="right", pady=(16, 0))

        self.hot_holder = theme.scroll_area(self)
        self.render_hot()

    def pick_city(self, city: str) -> None:
        self.city.set(city)
        self.render_hot()

    def render_hot(self) -> None:
        for child in self.hot_holder.winfo_children():
            child.destroy()
        tk.Label(
            self.hot_holder,
            text=f"{self.city.get()} · 热门推荐",
            bg=theme.BG,
            fg=theme.TEXT,
            font=theme.FONT_H2,
        ).pack(anchor="w", pady=(0, 10))
        items = self.services.store.list_room_types(self.city.get(), 2)
        if not items:
            theme.badge(self.hot_holder, "这个城市暂时没有在售房型", "warning").pack(
                anchor="w", pady=8
            )
            return
        for item in items:
            self._render_hot(self.hot_holder, item)

    def _render_hot(self, holder, item) -> None:
        try:
            price = self.services.pricing.get_price(item.room_type_id, date.today()).price_cents
        except NotFound:
            price = None
        remaining = self.services.inventory.query(item.room_type_id, date.today()).online_remaining
        _room_card(
            holder,
            item,
            remaining=remaining,
            price_cents=price,
            on_detail=lambda item=item: self.open_detail(item),
            on_book=lambda item=item: self.open_order(item),
        )

    def open_detail(self, item) -> None:
        self.app.selected_room_type = item
        from hotel.ui.customer_extra import (  # pylint: disable=import-outside-toplevel
            HotelDetailScreen,
        )

        self.app.show(HotelDetailScreen)

    def open_order(self, item) -> None:
        self.app.selected_room_type = item
        self.app.show(OrderScreen)

    @guarded
    def search(self) -> None:
        check_in = parse_date(self.check_in.get(), "check_in")
        check_out = parse_date(self.check_out.get(), "check_out")
        try:
            guests = int(self.guests.get().strip())
        except ValueError as exc:
            raise ValidationError("入住人数必须是正整数", field="guests") from exc
        results = self.services.store.list_room_types(self.city.get(), guests)
        self.app.search_params = {
            "check_in": check_in,
            "check_out": check_out,
            "guests": guests,
            "city": self.city.get(),
        }
        self.app.search_results = results
        self.app.show(ResultScreen)


class ResultScreen(Screen):
    title = "搜索结果"
    subtitle = "按门店分组展示，选择房型立即预订"

    def build(self) -> None:
        params = self.app.search_params or {}
        check_in = params.get("check_in")
        summary = "{} · {} 至 {} · {} 位".format(
            params.get("city", ""), check_in, params.get("check_out", ""), params.get("guests", "")
        )
        tk.Label(self, text=summary, bg=theme.BG, fg=theme.MUTED, font=theme.FONT_SMALL).pack(
            anchor="w", pady=(0, 10)
        )

        holder = theme.scroll_area(self)
        results = self.app.search_results or []
        if not results:
            theme.badge(holder, "没有符合条件的房型，换个城市或日期试试", "warning").pack(
                anchor="w", pady=8
            )
            return

        grouped: dict[str, list] = {}
        for item in results:
            grouped.setdefault(item.store_id, []).append(item)

        for items in grouped.values():
            first = items[0]
            block = tk.Frame(holder, bg=theme.BG)
            block.pack(fill="x", pady=(0, 14))
            head = tk.Frame(block, bg=theme.BG)
            head.pack(fill="x", pady=(0, 6))
            tk.Label(
                head, text=first.store_name, bg=theme.BG, fg=theme.TEXT, font=theme.FONT_H2
            ).pack(side="left")
            tk.Label(
                head,
                text=f"{first.city} · {first.district} · {len(items)} 个房型",
                bg=theme.BG,
                fg=theme.MUTED,
                font=theme.FONT_SMALL,
            ).pack(side="left", padx=10)
            for item in items:
                self._render(block, item, check_in)

    def _render(self, parent, item, check_in) -> None:
        remaining = 0
        price = None
        if check_in is not None:
            remaining = self.services.inventory.query(item.room_type_id, check_in).online_remaining
            try:
                price = self.services.pricing.get_price(item.room_type_id, check_in).price_cents
            except NotFound:
                price = None
        _room_card(
            parent,
            item,
            remaining=remaining,
            price_cents=price,
            on_detail=lambda item=item: self.detail(item),
            on_book=lambda item=item: self.book(item),
            show_store=False,
        )

    def detail(self, item) -> None:
        self.app.selected_room_type = item
        from hotel.ui.customer_extra import (  # pylint: disable=import-outside-toplevel
            HotelDetailScreen,
        )

        self.app.show(HotelDetailScreen)

    def book(self, item) -> None:
        self.app.selected_room_type = item
        self.app.show(OrderScreen)


class OrderScreen(Screen):
    title = "确认订单"
    subtitle = "核对房型、日期与金额后提交"

    def build(self) -> None:
        room_type = self.app.selected_room_type
        params = self.app.search_params
        self.nights = (params["check_out"] - params["check_in"]).days

        body = theme.card(self, room_type.room_type_name, fill="x", pady=(0, 14))
        head = tk.Frame(body, bg=theme.SURFACE)
        head.pack(fill="x")
        tk.Label(
            head,
            text=f"{room_type.store_name} · {room_type.city}{room_type.district}",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
        ).pack(anchor="w")
        tk.Label(
            head,
            text=f"{params['check_in']} 入住 · {params['check_out']} 离店 · 共 {self.nights} 晚",
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=theme.FONT_BODY,
        ).pack(anchor="w", pady=(6, 0))

        row = tk.Frame(body, bg=theme.SURFACE)
        row.pack(fill="x", pady=(14, 0))
        theme.field_label(row, "间数").pack(side="left", padx=(0, 8))
        self.qty = tk.IntVar(value=1)
        ttk.Spinbox(row, from_=1, to=5, textvariable=self.qty, width=5, style="App.TSpinbox").pack(
            side="left"
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
        theme.ghost(actions_row, "返回", self.back).pack(side="right", padx=(0, 10))

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
                detail.append(
                    f"{night}  周{WEEKDAYS[night.weekday()]}  {format_cents(price.price_cents)}"
                )
        except NotFound:
            self.summary_label.configure(text="所选日期尚未设置房价")
            return
        nights_text = "    ".join(detail)
        self.summary_label.configure(
            text=f"{nights_text}\n合计 {format_cents(total)}（不含线下加价）"
        )

    def back(self) -> None:
        self.app.show(ResultScreen)

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
        holder.place(relx=0.5, rely=0.38, anchor="center")

        box = tk.Frame(
            holder, bg=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1
        )
        box.pack()
        inner = tk.Frame(box, bg=theme.SURFACE)
        inner.pack(padx=48, pady=34)

        tk.Label(
            inner, text="待支付金额", bg=theme.SURFACE, fg=theme.MUTED, font=theme.FONT_SMALL
        ).pack(anchor="w")
        tk.Label(
            inner,
            text=format_cents(order.total_cents),
            bg=theme.SURFACE,
            fg=theme.DANGER,
            font=(theme.FAMILY, 28, "bold"),
        ).pack(anchor="w", pady=(2, 12))
        for label, value in (
            ("订单号", order.order_no),
            ("门店", order.store_name),
            ("入住", f"{order.check_in_date} 至 {order.check_out_date}"),
        ):
            line = tk.Frame(inner, bg=theme.SURFACE)
            line.pack(fill="x", pady=2)
            tk.Label(
                line,
                text=label,
                bg=theme.SURFACE,
                fg=theme.MUTED,
                font=theme.FONT_SMALL,
                width=6,
                anchor="w",
            ).pack(side="left")
            tk.Label(
                line, text=value, bg=theme.SURFACE, fg=theme.TEXT, font=theme.FONT_BODY, anchor="w"
            ).pack(side="left")

        theme.primary(inner, "确认支付", self.pay).pack(fill="x", pady=(20, 0))

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
        self.holder = theme.scroll_area(self)
        self.refresh()

    def refresh(self) -> None:
        for child in self.holder.winfo_children():
            child.destroy()
        orders = self.services.order.list_my_orders(self.app.session)
        if not orders:
            theme.badge(self.holder, "还没有订单，先去「房型查询」订一间吧", "warning").pack(
                anchor="w", pady=8
            )
            return
        for order in orders:
            self._render(order)

    def _render(self, order) -> None:
        box = tk.Frame(
            self.holder, bg=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1
        )
        box.pack(fill="x", pady=(0, 10))

        head = tk.Frame(box, bg=theme.SURFACE)
        head.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(
            head, text=order.store_name, bg=theme.SURFACE, fg=theme.TEXT, font=theme.FONT_H2
        ).pack(side="left")
        tone = {
            OrderStatus.PENDING_PAYMENT: "warning",
            OrderStatus.CONFIRMED: "accent",
            OrderStatus.CHECKED_IN: "success",
            OrderStatus.CHECKED_OUT: "accent",
            OrderStatus.CANCELLED: "danger",
            OrderStatus.NO_SHOW: "danger",
        }.get(order.status, "accent")
        theme.badge(
            head, ORDER_STATUS_LABEL.get(order.status.value, order.status.value), tone
        ).pack(side="left", padx=10)

        info = tk.Frame(box, bg=theme.SURFACE)
        info.pack(fill="x", padx=18, pady=(8, 0))
        tk.Label(
            info,
            text=f"{order.check_in_date} 至 {order.check_out_date} · 订单号 {order.order_no}",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
        ).pack(side="left")
        tk.Label(
            info,
            text=format_cents(order.total_cents),
            bg=theme.SURFACE,
            fg=theme.DANGER,
            font=(theme.FAMILY, 14, "bold"),
        ).pack(side="right")

        actions_row = tk.Frame(box, bg=theme.SURFACE)
        actions_row.pack(fill="x", padx=18, pady=(10, 14))
        if order.status is OrderStatus.PENDING_PAYMENT:
            theme.primary(actions_row, "去支付", lambda order=order: self.go_pay(order)).pack(
                side="right"
            )
            theme.ghost(actions_row, "取消", lambda order=order: self.cancel(order)).pack(
                side="right", padx=(0, 10)
            )
        elif order.status is OrderStatus.CHECKED_OUT:
            theme.primary(actions_row, "评价", lambda order=order: self.review(order)).pack(
                side="right"
            )
        elif order.status in (OrderStatus.CONFIRMED, OrderStatus.NO_SHOW):
            theme.ghost(actions_row, "取消订单", lambda order=order: self.cancel(order)).pack(
                side="right"
            )

    @guarded
    def go_pay(self, order) -> None:
        self.app.current_order = order
        self.app.show(PaymentScreen)

    @guarded
    def cancel(self, order) -> None:
        reason = simpledialog.askstring("取消订单", "请填写取消原因", initialvalue="行程有变")
        if reason is None:
            return
        self.services.order.cancel_order(self.app.session, order.id, reason)
        self.refresh()

    @guarded
    def review(self, order) -> None:
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
