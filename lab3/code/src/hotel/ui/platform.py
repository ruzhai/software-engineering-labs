"""片区负责人端：片区概览、价格区间下发、店长名册。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from hotel.core.money import cents_to_yuan, yuan_to_cents
from hotel.ui import theme
from hotel.ui.app import Screen
from hotel.ui.common import guarded, parse_date


class RegionScreen(Screen):
    title = "片区概览"
    subtitle = "近 30 天各门店经营情况"

    def build(self) -> None:
        self.kpi = tk.Frame(self, bg=theme.BG)
        self.kpi.pack(fill="x")

        body = theme.card(self, "门店汇总", fill="both", expand=True)
        self.tree = theme.table(
            body,
            ("门店", "城市", "营业状态", "订单数", "入住率", "平均评分"),
            widths=[150, 110, 120, 110, 110, 110],
            height=12,
        )
        actions = theme.actions(body)
        theme.ghost(actions, "刷新", self.refresh).pack(side="left")
        self.refresh()

    def refresh(self) -> None:
        for child in self.kpi.winfo_children():
            child.destroy()
        end = date.today()
        start = end - timedelta(days=30)
        rows = []
        for store in self.services.store.list_stores_of_area(self.app.session):
            performance = self.services.performance.snapshot_performance(
                self.app.session, store_id=store.id, start=start, end=end
            )
            rows.append((store, performance))

        total_orders = sum(item[1].order_count for item in rows)
        avg_score = round(sum(item[1].avg_score for item in rows) / len(rows), 2) if rows else 0.0
        theme.kpi_row(
            self.kpi,
            [
                ("门店数", str(len(rows)), "本片区在营门店", theme.TEXT),
                ("近 30 天订单", str(total_orders), "不含已取消", theme.ACCENT),
                ("平均评分", f"{avg_score}", "取自已发布评价", theme.SUCCESS),
                ("统计区间", f"{start:%m-%d}", f"至 {end:%m-%d}", theme.MUTED),
            ],
        )

        self.tree.delete(*self.tree.get_children())
        for store, performance in rows:
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
    subtitle = "向本片区门店下发可售价格区间"

    def build(self) -> None:
        self.stores = self.services.store.list_stores_of_area(self.app.session)
        self.store_names = [store.name for store in self.stores]
        self.selected_store = tk.StringVar(value=self.store_names[0] if self.store_names else "")

        form = theme.card(self, "下发价格区间", fill="x", pady=(0, 14))
        grid = tk.Frame(form, bg=theme.SURFACE)
        grid.pack(fill="x")
        theme.field_label(grid, "门店").grid(row=0, column=0, sticky="e", padx=(0, 8))
        ttk.Combobox(
            grid,
            textvariable=self.selected_store,
            values=self.store_names,
            state="readonly",
            width=14,
            style="App.TCombobox",
        ).grid(row=0, column=1, sticky="w")

        self.effective = tk.StringVar(value=date.today().isoformat())
        self.low = tk.StringVar(value="200")
        self.high = tk.StringVar(value="800")
        theme.field_label(grid, "生效日期").grid(row=0, column=2, sticky="e", padx=(20, 8))
        theme.entry(grid, self.effective, 12).grid(row=0, column=3, sticky="w")
        theme.field_label(grid, "下限（元）").grid(row=0, column=4, sticky="e", padx=(20, 8))
        theme.entry(grid, self.low, 8).grid(row=0, column=5, sticky="w")
        theme.field_label(grid, "上限（元）").grid(row=0, column=6, sticky="e", padx=(20, 8))
        theme.entry(grid, self.high, 8).grid(row=0, column=7, sticky="w")

        actions_row = theme.actions(form)
        theme.primary(actions_row, "下发", self.submit).pack(side="right")

        body = theme.card(self, "已下发的区间", fill="both", expand=True)
        self.tree = theme.table(
            body, ("生效日期", "下限", "上限"), widths=[180, 160, 160], height=12
        )
        actions = theme.actions(body)
        theme.ghost(actions, "刷新", self.refresh).pack(side="left")
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
    subtitle = "本片区各店店长与账号状态"

    def build(self) -> None:
        body = theme.card(self, "店长名册", fill="both", expand=True)
        self.tree = theme.table(body, ("姓名", "手机号", "状态"), widths=[200, 200, 160], height=14)
        actions = theme.actions(body)
        theme.primary(actions, "停用所选店长", self.disable).pack(side="right")
        theme.ghost(actions, "刷新", self.refresh).pack(side="left")
        self.managers: dict[str, object] = {}
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
