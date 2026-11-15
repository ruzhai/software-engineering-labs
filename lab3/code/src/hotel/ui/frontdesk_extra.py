"""前台端补充界面：客房打扫、前台开单。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from hotel.core.ids import new_id
from hotel.core.money import format_cents
from hotel.m02_store.model import RoomStatus
from hotel.m05_order.service import RoomRequest
from hotel.ui.app import Screen
from hotel.ui.common import guarded, make_table, parse_date

CLEANING_STATES = (RoomStatus.CHECKED_OUT, RoomStatus.CLEANING)


class HousekeepingScreen(Screen):
    title = "客房打扫"

    def build(self) -> None:
        ttk.Label(self, text="待打扫房间", padding=8).pack(anchor="w", padx=8)
        self.tree = make_table(self, ("房型", "房号", "状态"))
        self.rooms: dict[str, object] = {}
        ttk.Button(self, text="打扫完成", command=self.finish).pack(pady=8)
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

    def build(self) -> None:
        form = ttk.LabelFrame(self, text="线下开单（占用线下保留额度）", padding=14)
        form.pack(fill="x", padx=16, pady=12)

        self.phone = tk.StringVar()
        self.customer_name = tk.StringVar(value="未查询")
        self.room_type_names: list[str] = []
        self.room_type_ids: dict[str, str] = {}
        self.selected_type = tk.StringVar()
        self.qty = tk.IntVar(value=1)
        today = date.today()
        self.check_in = tk.StringVar(value=today.isoformat())
        self.check_out = tk.StringVar(value=(today + timedelta(days=1)).isoformat())

        ttk.Label(form, text="顾客手机号").grid(row=0, column=0, sticky="e", padx=6)
        ttk.Entry(form, textvariable=self.phone, width=16).grid(row=0, column=1)
        ttk.Button(form, text="查顾客", command=self.lookup).grid(row=0, column=2, padx=6)
        ttk.Label(form, textvariable=self.customer_name, foreground="#2f855a").grid(
            row=0, column=3, columnspan=2, sticky="w"
        )

        for room_type in self.services.store.list_room_types_of_store(self.app.session.store_id):
            self.room_type_names.append(room_type.name)
            self.room_type_ids[room_type.name] = room_type.id
        if self.room_type_names:
            self.selected_type.set(self.room_type_names[0])

        ttk.Label(form, text="房型").grid(row=1, column=0, sticky="e", padx=6, pady=6)
        ttk.Combobox(
            form,
            textvariable=self.selected_type,
            values=self.room_type_names,
            state="readonly",
            width=14,
        ).grid(row=1, column=1)
        ttk.Label(form, text="间数").grid(row=1, column=2, sticky="e", padx=6)
        ttk.Spinbox(form, from_=1, to=5, textvariable=self.qty, width=5).grid(row=1, column=3)

        ttk.Label(form, text="入住").grid(row=2, column=0, sticky="e", padx=6)
        ttk.Entry(form, textvariable=self.check_in, width=14).grid(row=2, column=1, pady=6)
        ttk.Label(form, text="离店").grid(row=2, column=2, sticky="e", padx=6)
        ttk.Entry(form, textvariable=self.check_out, width=14).grid(row=2, column=3)

        ttk.Button(form, text="确认开单", command=self.create).grid(
            row=3, column=0, columnspan=4, pady=10, sticky="ew"
        )

        ttk.Label(self, text="说明：线下开单从当日保留额度扣减，不占用线上库存。").pack(
            anchor="w", padx=16
        )

    @guarded
    def lookup(self) -> None:
        user = self.services.account.find_customer_by_phone(
            self.app.session, self.phone.get().strip()
        )
        self.customer_name.set(f"{user.name}（{user.phone}）")
        self.customer_id = user.id

    @guarded
    def create(self) -> None:
        customer_id = getattr(self, "customer_id", None)
        if customer_id is None:
            messagebox.showinfo("提示", "请先查询顾客")
            return
        name = self.selected_type.get()
        room_type_id = self.room_type_ids.get(name)
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
