"""前台端：房态看板、办理入住、办理退房。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, simpledialog

from hotel.core.money import format_cents
from hotel.m02_store.model import RoomStatus
from hotel.m05_order.model import OrderStatus
from hotel.ui import theme
from hotel.ui.app import Screen
from hotel.ui.common import guarded, parse_date

STATUS_LABEL = {
    RoomStatus.FREE: "空闲",
    RoomStatus.RESERVED: "已预定",
    RoomStatus.OCCUPIED: "已入住",
    RoomStatus.CHECKED_OUT: "已退房",
    RoomStatus.CLEANING: "需打扫",
    RoomStatus.REPAIRING: "维修中",
}


def _rooms_of_store(services, store_id: str):
    for room_type in services.store.list_room_types_of_store(store_id):
        for room in services.store.list_rooms(room_type.id):
            yield room_type, room


class BoardScreen(Screen):
    title = "房态看板"
    subtitle = "推进房态，维修中的房间会同步压减可售上限"

    def build(self) -> None:
        self.kpi = tk.Frame(self, bg=theme.BG)
        self.kpi.pack(fill="x")

        body = theme.card(self, "全部房间", fill="both", expand=True)
        self.tree = theme.table(
            body, ("房型", "房号", "状态", "预计修复"), widths=[160, 120, 120, 140], height=14
        )
        actions_row = theme.actions(body)
        theme.primary(actions_row, "设为维修", self.mark_repairing).pack(side="right")
        theme.ghost(actions_row, "修复完成", self.mark_fixed).pack(side="right", padx=(0, 10))
        theme.ghost(actions_row, "打扫完成", self.mark_clean).pack(side="right", padx=(0, 10))
        theme.ghost(actions_row, "刷新", self.refresh).pack(side="left")

        self.rooms: dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        for child in self.kpi.winfo_children():
            child.destroy()
        pairs = list(_rooms_of_store(self.services, self.app.session.store_id))
        counts = {status: 0 for status in RoomStatus}
        for _, room in pairs:
            counts[room.status] += 1
        theme.kpi_row(
            self.kpi,
            [
                ("空闲", str(counts[RoomStatus.FREE]), "可直接排房", theme.SUCCESS),
                ("已预定", str(counts[RoomStatus.RESERVED]), "等待入住", theme.ACCENT),
                ("已入住", str(counts[RoomStatus.OCCUPIED]), "在住房间", theme.ACCENT),
                ("需打扫", str(counts[RoomStatus.CLEANING]), "待客房清理", theme.WARNING),
                ("维修中", str(counts[RoomStatus.REPAIRING]), "已从可售上限扣除", theme.DANGER),
            ],
        )

        self.tree.delete(*self.tree.get_children())
        self.rooms.clear()
        for room_type, room in pairs:
            row = self.tree.insert(
                "",
                "end",
                values=(
                    room_type.name,
                    room.room_no,
                    STATUS_LABEL[room.status],
                    room.repair_until or "",
                ),
            )
            self.rooms[row] = room

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个房间")
            return None
        return self.rooms.get(selection[0])

    @guarded
    def mark_repairing(self) -> None:
        room = self._selected()
        if room is None:
            return
        text = simpledialog.askstring(
            "转入维修",
            "预计修复日期（YYYY-MM-DD）",
            initialvalue=(date.today() + timedelta(days=3)).isoformat(),
        )
        if text is None:
            return
        self.services.room.change_room_status(
            self.app.session, room.id, RoomStatus.REPAIRING, parse_date(text, "repair_until")
        )
        self.refresh()

    @guarded
    def mark_fixed(self) -> None:
        room = self._selected()
        if room is None:
            return
        self.services.room.change_room_status(self.app.session, room.id, RoomStatus.FREE)
        self.refresh()

    @guarded
    def mark_clean(self) -> None:
        room = self._selected()
        if room is None:
            return
        self.services.room.change_room_status(self.app.session, room.id, RoomStatus.FREE)
        self.refresh()


class CheckInScreen(Screen):
    title = "办理入住"
    subtitle = "为已确认订单分配房间并办理入住"

    def build(self) -> None:
        body = theme.card(self, "待入住订单", fill="both", expand=True)
        self.tree = theme.table(
            body,
            ("订单号", "入住", "离店", "金额", "房型"),
            widths=[200, 110, 110, 110, 130],
            height=14,
        )
        actions_row = theme.actions(body)
        theme.primary(actions_row, "分配房间并入住", self.check_in).pack(side="right")
        theme.ghost(actions_row, "刷新", self.refresh).pack(side="left")

        self.orders: dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.orders.clear()
        store_id = self.app.session.store_id
        type_names = {
            room_type.id: room_type.name
            for room_type in self.services.store.list_room_types_of_store(store_id)
        }
        for order in self.services.order.list_store_orders(self.app.session, store_id):
            if order.status is not OrderStatus.CONFIRMED:
                continue
            room_type_id = order.items[0].room_type_id if order.items else ""
            row = self.tree.insert(
                "",
                "end",
                values=(
                    order.order_no,
                    order.check_in_date,
                    order.check_out_date,
                    format_cents(order.total_cents),
                    type_names.get(room_type_id, ""),
                ),
            )
            self.orders[row] = order

    @guarded
    def check_in(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一笔订单")
            return
        order = self.orders[selection[0]]
        if not order.items:
            messagebox.showinfo("提示", "订单没有明细")
            return
        room_type_id = order.items[0].room_type_id
        required = sum(item.qty for item in order.items if item.stay_date == order.check_in_date)
        free_rooms = [
            room
            for room in self.services.store.list_rooms(room_type_id)
            if room.status is RoomStatus.FREE
        ]
        if len(free_rooms) < required:
            messagebox.showwarning(
                "没有可用房间",
                f"这笔订单需要 {required} 间空闲房间，当前只有 {len(free_rooms)} 间",
            )
            return
        chosen = free_rooms[:required]
        for room in chosen:
            self.services.room.assign_room(self.app.session, order.id, room.id)
        self.services.room.check_in(self.app.session, order.id)
        messagebox.showinfo("入住成功", "已分配房间：" + "、".join(r.room_no for r in chosen))
        self.refresh()


class CheckOutScreen(Screen):
    title = "办理退房"
    subtitle = "退房后房间自动转为需打扫"

    def build(self) -> None:
        body = theme.card(self, "在住订单", fill="both", expand=True)
        self.tree = theme.table(
            body, ("订单号", "入住", "离店", "金额"), widths=[220, 120, 120, 120], height=14
        )
        actions_row = theme.actions(body)
        theme.primary(actions_row, "确认退房", self.check_out).pack(side="right")
        theme.ghost(actions_row, "刷新", self.refresh).pack(side="left")

        self.orders: dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.orders.clear()
        store_id = self.app.session.store_id
        for order in self.services.order.list_store_orders(self.app.session, store_id):
            if order.status is not OrderStatus.CHECKED_IN:
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
    def check_out(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一笔订单")
            return
        order = self.orders[selection[0]]
        self.services.room.check_out(self.app.session, order.id)
        messagebox.showinfo("退房完成", "房间已转为需打扫")
        self.refresh()
