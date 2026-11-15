"""前台端补充界面：客房打扫、前台开单。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from hotel.core.ids import new_id
from hotel.core.money import format_cents
from hotel.m02_store.model import RoomStatus
from hotel.m05_order.service import RoomRequest
from hotel.ui import theme
from hotel.ui.app import Screen
from hotel.ui.common import guarded, parse_date

CLEANING_STATES = (RoomStatus.CHECKED_OUT, RoomStatus.CLEANING)


class HousekeepingScreen(Screen):
    title = "客房打扫"
    subtitle = "打扫完成前，房间不能回到空闲状态"

    def build(self) -> None:
        body = theme.card(self, "待打扫房间", fill="both", expand=True)
        self.tree = theme.table(body, ("房型", "房号", "状态"), widths=[200, 160, 160], height=14)
        actions_row = theme.actions(body)
        theme.primary(actions_row, "打扫完成", self.finish).pack(side="right")
        theme.ghost(actions_row, "刷新", self.refresh).pack(side="left")

        self.rooms: dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rooms.clear()
        for room_type in self.services.store.list_room_types_of_store(self.app.session.store_id):
            for room in self.services.store.list_rooms(room_type.id):
                if room.status not in CLEANING_STATES:
                    continue
                row = self.tree.insert(
                    "", "end", values=(room_type.name, room.room_no, room.status.value)
                )
                self.rooms[row] = room
        if not self.rooms:
            theme.badge(self.tree.master, "当前没有待打扫房间", "success").pack(
                anchor="w", pady=(8, 0)
            )

    @guarded
    def finish(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个房间")
            return
        room = self.rooms[selection[0]]
        self.services.room.change_room_status(self.app.session, room.id, RoomStatus.FREE)
        self.refresh()


class WalkInScreen(Screen):
    title = "前台开单"
    subtitle = "线下开单占用保留额度，不扣线上库存"

    def build(self) -> None:
        body = theme.card(self, "线下开单", fill="x", pady=(0, 14))

        self.phone = tk.StringVar()
        self.customer_id: str | None = None
        self.customer_name = tk.StringVar(value="尚未查询")
        self.qty = tk.IntVar(value=1)
        today = date.today()
        self.check_in = tk.StringVar(value=today.isoformat())
        self.check_out = tk.StringVar(value=(today + timedelta(days=1)).isoformat())

        room_types = self.services.store.list_room_types_of_store(self.app.session.store_id)
        self.room_type_ids = {room_type.name: room_type.id for room_type in room_types}
        self.selected_type = tk.StringVar(value=room_types[0].name if room_types else "")

        grid = tk.Frame(body, bg=theme.SURFACE)
        grid.pack(fill="x")

        theme.field_label(grid, "顾客手机号").grid(row=0, column=0, sticky="e", padx=(0, 8))
        theme.entry(grid, self.phone, 16).grid(row=0, column=1, sticky="w")
        theme.ghost(grid, "查顾客", self.lookup).grid(row=0, column=2, padx=10)
        tk.Label(
            grid,
            textvariable=self.customer_name,
            bg=theme.SURFACE,
            fg=theme.SUCCESS,
            font=theme.FONT_BODY,
        ).grid(row=0, column=3, columnspan=3, sticky="w")

        theme.field_label(grid, "房型").grid(row=1, column=0, sticky="e", pady=(14, 0))
        ttk.Combobox(
            grid,
            textvariable=self.selected_type,
            values=list(self.room_type_ids),
            state="readonly",
            width=14,
            style="App.TCombobox",
        ).grid(row=1, column=1, sticky="w", pady=(14, 0))
        theme.field_label(grid, "间数").grid(
            row=1, column=2, sticky="e", pady=(14, 0), padx=(18, 8)
        )
        ttk.Spinbox(grid, from_=1, to=5, textvariable=self.qty, width=5, style="App.TSpinbox").grid(
            row=1, column=3, sticky="w", pady=(14, 0)
        )

        theme.field_label(grid, "入住").grid(row=2, column=0, sticky="e", pady=(12, 0))
        theme.entry(grid, self.check_in, 14).grid(row=2, column=1, sticky="w", pady=(12, 0))
        theme.field_label(grid, "离店").grid(
            row=2, column=2, sticky="e", pady=(12, 0), padx=(18, 8)
        )
        theme.entry(grid, self.check_out, 14).grid(row=2, column=3, sticky="w", pady=(12, 0))

        actions_row = theme.actions(body, pady=(18, 0))
        theme.primary(actions_row, "确认开单", self.create).pack(side="right")

        note = theme.card(self, "说明", fill="x")
        tk.Label(
            note,
            text="线下开单从当日保留额度扣减；保留额度不足时应改走线上渠道。",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
            anchor="w",
        ).pack(fill="x")

    @guarded
    def lookup(self) -> None:
        user = self.services.account.find_customer_by_phone(
            self.app.session, self.phone.get().strip()
        )
        self.customer_name.set(f"{user.name}（{user.phone}）")
        self.customer_id = user.id

    @guarded
    def create(self) -> None:
        customer_id = self.customer_id
        if customer_id is None:
            messagebox.showinfo("提示", "请先查询顾客")
            return
        room_type_id = self.room_type_ids.get(self.selected_type.get())
        if room_type_id is None:
            messagebox.showinfo("提示", "请选择房型")
            return
        order = self.services.order.create_walk_in_order(
            self.app.session,
            store_id=self.app.session.store_id,
            customer_id=customer_id,
            request_no=new_id("walkin"),
            items=[RoomRequest(room_type_id, self.qty.get())],
            check_in=parse_date(self.check_in.get(), "check_in"),
            check_out=parse_date(self.check_out.get(), "check_out"),
        )
        messagebox.showinfo(
            "开单成功", f"订单 {order.order_no}，金额 {format_cents(order.total_cents)}"
        )
