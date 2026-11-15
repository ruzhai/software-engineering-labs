"""片区负责人端：片区概览、价格区间下发、店长名册。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from hotel.core.money import cents_to_yuan, yuan_to_cents
from hotel.ui.app import Screen
from hotel.ui.common import guarded, make_table, parse_date


class RegionScreen(Screen):
    title = "片区概览"

    def build(self) -> None:
        ttk.Label(self, text="近 30 天各店经营情况", padding=8).pack(anchor="w", padx=8)
        self.tree = make_table(self, ("门店", "城市", "营业状态", "订单数", "入住率", "平均评分"))
        ttk.Button(self, text="刷新", command=self.refresh).pack(pady=8)
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        end = date.today()
        start = end - timedelta(days=30)
        for store in self.services.store.list_stores_of_area(self.app.session):
            performance = self.services.performance.snapshot_performance(
                self.app.session, store_id=store.id, start=start, end=end
            )
            self.tree.insert(
                "",
                "end",
                values=(
                    store.name,
                    store.city,
                    store.status.value,
                    performance.order_count,
                    f"{performance.occupancy_rate:.1%}",
                    performance.avg_score,
                ),
            )


class PriceRangeScreen(Screen):
    title = "价格区间"

    def build(self) -> None:
        self.stores = self.services.store.list_stores_of_area(self.app.session)
        self.store_names = [store.name for store in self.stores]
        self.selected_store = tk.StringVar(value=self.store_names[0] if self.store_names else "")

        form = ttk.LabelFrame(self, text="下发价格区间", padding=12)
        form.pack(fill="x", padx=16, pady=10)
        ttk.Label(form, text="门店").grid(row=0, column=0, sticky="e", padx=6)
        ttk.Combobox(
            form,
            textvariable=self.selected_store,
            values=self.store_names,
            state="readonly",
            width=14,
        ).grid(row=0, column=1, padx=6)
        self.effective = tk.StringVar(value=date.today().isoformat())
        self.low = tk.StringVar(value="200")
        self.high = tk.StringVar(value="800")
        ttk.Label(form, text="生效日期").grid(row=0, column=2, sticky="e", padx=6)
        ttk.Entry(form, textvariable=self.effective, width=12).grid(row=0, column=3)
        ttk.Label(form, text="下限(元)").grid(row=0, column=4, sticky="e", padx=6)
        ttk.Entry(form, textvariable=self.low, width=8).grid(row=0, column=5)
        ttk.Label(form, text="上限(元)").grid(row=0, column=6, sticky="e", padx=6)
        ttk.Entry(form, textvariable=self.high, width=8).grid(row=0, column=7)
        ttk.Button(form, text="下发", command=self.submit).grid(row=0, column=8, padx=8)

        ttk.Label(self, text="已下发的区间", padding=6).pack(anchor="w", padx=16)
        self.tree = make_table(self, ("生效日期", "下限", "上限"))
        ttk.Button(self, text="刷新", command=self.refresh).pack(pady=8)
        self.refresh()

    def _selected(self):
        name = self.selected_store.get()
        return next((store for store in self.stores if store.name == name), None)

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        store = self._selected()
        if store is None:
            return
        for price_range in self.services.pricing.list_price_ranges(self.app.session, store.id):
            self.tree.insert(
                "",
                "end",
                values=(
                    price_range.effective_date,
                    cents_to_yuan(price_range.min_cents),
                    cents_to_yuan(price_range.max_cents),
                ),
            )

    @guarded
    def submit(self) -> None:
        store = self._selected()
        if store is None:
            messagebox.showinfo("提示", "请先选择门店")
            return
        self.services.pricing.set_price_range(
            self.app.session,
            store_id=store.id,
            effective_date=parse_date(self.effective.get(), "effective_date"),
            min_cents=yuan_to_cents(self.low.get()),
            max_cents=yuan_to_cents(self.high.get()),
        )
        messagebox.showinfo("已下发", "价格区间已生效")
        self.refresh()


class RosterScreen(Screen):
    title = "店长名册"

    def build(self) -> None:
        ttk.Label(self, text="本片区店长", padding=8).pack(anchor="w", padx=8)
        self.tree = make_table(self, ("姓名", "手机号", "状态"))
        self.managers: dict[str, object] = {}
        actions = ttk.Frame(self)
        actions.pack(pady=8)
        ttk.Button(actions, text="刷新", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(actions, text="停用所选店长", command=self.disable).pack(side="left", padx=4)
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.managers.clear()
        for user in self.services.account.list_store_managers(self.app.session):
            row = self.tree.insert("", "end", values=(user.name, user.phone, user.status.value))
            self.managers[row] = user

    @guarded
    def disable(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一位店长")
            return
        user = self.managers[selection[0]]
        self.services.account.disable_user(self.app.session, user.id)
        self.refresh()
