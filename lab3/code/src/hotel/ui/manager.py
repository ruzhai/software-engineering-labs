"""店长端：改价与审批。"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from hotel.core.money import cents_to_yuan, format_cents, yuan_to_cents
from hotel.ui.app import Screen
from hotel.ui.common import guarded, parse_date


class PricingScreen(Screen):
    title = "改价与审批"

    def build(self) -> None:
        box = ttk.LabelFrame(self, text="设置房价", padding=12)
        box.pack(fill="x", padx=16, pady=10)

        self.room_types = self.services.store.list_room_types_of_store(self.app.session.store_id)
        self.room_type_names = [item.name for item in self.room_types]
        self.selected_type = tk.StringVar(
            value=self.room_type_names[0] if self.room_type_names else ""
        )
        self.start = tk.StringVar(value=date.today().isoformat())
        self.end = tk.StringVar(value=date.today().isoformat())
        self.price = tk.StringVar(value="500")

        ttk.Label(box, text="房型").grid(row=0, column=0, padx=6, sticky="e")
        ttk.Combobox(
            box, textvariable=self.selected_type, values=self.room_type_names, state="readonly"
        ).grid(row=0, column=1, padx=6)
        ttk.Label(box, text="开始").grid(row=0, column=2, padx=6, sticky="e")
        ttk.Entry(box, textvariable=self.start, width=12).grid(row=0, column=3, padx=6)
        ttk.Label(box, text="结束").grid(row=0, column=4, padx=6, sticky="e")
        ttk.Entry(box, textvariable=self.end, width=12).grid(row=0, column=5, padx=6)
        ttk.Label(box, text="单价（元）").grid(row=0, column=6, padx=6, sticky="e")
        ttk.Entry(box, textvariable=self.price, width=10).grid(row=0, column=7, padx=6)
        ttk.Button(box, text="保存", command=self.save_price).grid(row=0, column=8, padx=8)

        ttk.Label(self, text="待审批的改价申请", padding=6).pack(anchor="w", padx=16)
        self.tree = ttk.Treeview(
            self, columns=("日期", "原价", "申请价", "申请人"), show="headings", height=10
        )
        for column in ("日期", "原价", "申请价", "申请人"):
            self.tree.heading(column, text=column)
            self.tree.column(column, width=160, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=16, pady=6)

        actions = ttk.Frame(self)
        actions.pack(pady=8)
        ttk.Button(actions, text="刷新", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(actions, text="通过", command=self.approve).pack(side="left", padx=4)
        ttk.Button(actions, text="驳回", command=self.reject).pack(side="left", padx=4)

        self.requests: dict[str, object] = {}
        self.refresh()

    def _selected_room_type(self):
        name = self.selected_type.get()
        return next((item for item in self.room_types if item.name == name), None)

    @guarded
    def save_price(self) -> None:
        room_type = self._selected_room_type()
        if room_type is None:
            messagebox.showinfo("提示", "请先选择房型")
            return
        start = parse_date(self.start.get(), "start")
        end = parse_date(self.end.get(), "end")
        cents = yuan_to_cents(self.price.get())
        days = self.services.pricing.set_prices(
            self.app.session,
            room_type_id=room_type.id,
            start=start,
            end=end,
            price_cents=cents,
        )
        messagebox.showinfo("已保存", f"{days} 天房价已更新为 {format_cents(cents)}")

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.requests.clear()
        for request in self.services.pricing.list_pending_requests(
            self.app.session, self.app.session.store_id
        ):
            row = self.tree.insert(
                "",
                "end",
                values=(
                    request.price_date,
                    cents_to_yuan(request.old_cents),
                    cents_to_yuan(request.new_cents),
                    request.applicant[-6:],
                ),
            )
            self.requests[row] = request

    @guarded
    def approve(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一条申请")
            return
        self.services.pricing.approve_price_change(self.app.session, self.requests[selection[0]].id)
        self.refresh()

    @guarded
    def reject(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一条申请")
            return
        self.services.pricing.reject_price_change(self.app.session, self.requests[selection[0]].id)
        self.refresh()
