"""前台端：房态看板、办理入住、办理退房。"""

from __future__ import annotations

from datetime import date, timedelta
from tkinter import messagebox, simpledialog, ttk

from hotel.core.money import format_cents
from hotel.m02_store.model import RoomStatus
from hotel.m05_order.model import OrderStatus
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

    def build(self) -> None:
        columns = ("房型", "房号", "状态", "预计修复")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=16)
        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=160, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=12, pady=8)

        actions = ttk.Frame(self)
        actions.pack(pady=8)
        ttk.Button(actions, text="刷新", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(actions, text="设为维修", command=self.mark_repairing).pack(side="left", padx=4)
        ttk.Button(actions, text="修复完成", command=self.mark_fixed).pack(side="left", padx=4)
        ttk.Button(actions, text="打扫完成", command=self.mark_clean).pack(side="left", padx=4)

        self.rooms: dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rooms.clear()
        for room_type, room in _rooms_of_store(self.services, self.app.session.store_id):
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
        if not self.rooms:
            self.tree.insert("", "end", values=("（本店还没有房间）", "", "", ""))

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

    def build(self) -> None:
        columns = ("订单号", "入住", "离店", "金额", "房型")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=14)
        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=160, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=12, pady=8)

        actions = ttk.Frame(self)
        actions.pack(pady=8)
        ttk.Button(actions, text="刷新", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(actions, text="分配房间并入住", command=self.check_in).pack(side="left", padx=4)

        self.orders: dict[str, object] = {}
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.orders.clear()
        store_id = self.app.session.store_id
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
                    room_type_id[-6:],
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

    def build(self) -> None:
        columns = ("订单号", "入住", "离店", "金额")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=14)
        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=180, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=12, pady=8)

        actions = ttk.Frame(self)
        actions.pack(pady=8)
        ttk.Button(actions, text="刷新", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(actions, text="确认退房", command=self.check_out).pack(side="left", padx=4)

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
