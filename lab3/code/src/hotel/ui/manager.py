"""店长端：改价与审批。"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from hotel.core.money import cents_to_yuan, format_cents, yuan_to_cents
from hotel.ui import theme
from hotel.ui.app import Screen
from hotel.ui.common import guarded, parse_date


class PricingScreen(Screen):
    title = "改价与审批"
    subtitle = "在平台下发的价格区间内调整房价"

    def build(self) -> None:
        form = theme.card(self, "设置房价", fill="x", pady=(0, 14))

        self.room_types = self.services.store.list_room_types_of_store(self.app.session.store_id)
        self.room_type_names = [item.name for item in self.room_types]
        self.selected_type = tk.StringVar(
            value=self.room_type_names[0] if self.room_type_names else ""
        )
        self.start = tk.StringVar(value=date.today().isoformat())
        self.end = tk.StringVar(value=date.today().isoformat())
        self.price = tk.StringVar(value="500")

        grid = tk.Frame(form, bg=theme.SURFACE)
        grid.pack(fill="x")
        theme.field_label(grid, "房型").grid(row=0, column=0, sticky="e", padx=(0, 8))
        ttk.Combobox(
            grid,
            textvariable=self.selected_type,
            values=self.room_type_names,
            state="readonly",
            width=14,
            style="App.TCombobox",
        ).grid(row=0, column=1, sticky="w")
        theme.field_label(grid, "开始").grid(row=0, column=2, sticky="e", padx=(20, 8))
        theme.entry(grid, self.start, 12).grid(row=0, column=3, sticky="w")
        theme.field_label(grid, "结束").grid(row=0, column=4, sticky="e", padx=(20, 8))
        theme.entry(grid, self.end, 12).grid(row=0, column=5, sticky="w")
        theme.field_label(grid, "单价（元）").grid(row=0, column=6, sticky="e", padx=(20, 8))
        theme.entry(grid, self.price, 8).grid(row=0, column=7, sticky="w")

        actions_row = theme.actions(form)
        theme.primary(actions_row, "保存", self.save_price).pack(side="right")

        body = theme.card(self, "待审批的改价申请", fill="both", expand=True)
        self.tree = theme.table(
            body, ("日期", "原价", "申请价", "申请人"), widths=[160, 140, 140, 160], height=10
        )
        actions = theme.actions(body)
        theme.primary(actions, "通过", self.approve).pack(side="right")
        theme.ghost(actions, "驳回", self.reject).pack(side="right", padx=(0, 10))
        theme.ghost(actions, "刷新", self.refresh).pack(side="left")

        self.requests: dict[str, object] = {}
        self.refresh()

    def _applicant_name(self, user_id: str) -> str:
        try:
            return self.services.account.get_user(user_id).name
        except Exception:  # pylint: disable=broad-exception-caught
            return user_id[-6:]

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
                    self._applicant_name(request.applicant),
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
