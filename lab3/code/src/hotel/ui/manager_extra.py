"""店长端与审计相关界面：审批中心、员工名册、消息中心、操作日志。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from hotel.core.money import cents_to_yuan
from hotel.ui import theme
from hotel.ui.app import Screen
from hotel.ui.common import guarded


class ApprovalScreen(Screen):
    title = "审批中心"
    subtitle = "店长统一处理改价、取消与改期申请"

    def build(self) -> None:
        body = theme.card(self, "待审批事项", fill="both", expand=True)
        notebook = ttk.Notebook(body, style="App.TNotebook")
        notebook.pack(fill="both", expand=True)
        self.notebook = notebook

        self.price_tab, self.price_tree = self._tab(
            notebook, "改价申请", ("日期", "原价", "申请价")
        )
        self.cancel_tab, self.cancel_tree = self._tab(notebook, "取消申请", ("订单号", "原因"))
        self.modify_tab, self.modify_tree = self._tab(
            notebook, "改期申请", ("订单号", "原价", "新价", "新入住", "新离店")
        )

        self.price_items: dict[str, object] = {}
        self.cancel_items: dict[str, object] = {}
        self.modify_items: dict[str, object] = {}

        actions = theme.actions(body)
        theme.primary(actions, "通过", self.approve).pack(side="right")
        theme.ghost(actions, "驳回", self.reject).pack(side="right", padx=(0, 10))
        theme.ghost(actions, "刷新", self.refresh).pack(side="left")

        self.refresh()

    def _tab(self, notebook, title: str, columns: tuple[str, ...]):
        frame = tk.Frame(notebook, bg=theme.SURFACE)
        tree = theme.table(frame, columns, widths=[190] * len(columns), height=12)
        notebook.add(frame, text=title)
        return frame, tree

    def refresh(self) -> None:
        store_id = self.app.session.store_id
        order_numbers = {
            order.id: order.order_no
            for order in self.services.order.list_store_orders(self.app.session, store_id)
        }

        self.price_tree.delete(*self.price_tree.get_children())
        self.price_items.clear()
        for request in self.services.pricing.list_pending_requests(self.app.session, store_id):
            row = self.price_tree.insert(
                "",
                "end",
                values=(
                    request.price_date,
                    cents_to_yuan(request.old_cents),
                    cents_to_yuan(request.new_cents),
                ),
            )
            self.price_items[row] = request

        self.cancel_tree.delete(*self.cancel_tree.get_children())
        self.cancel_items.clear()
        for request in self.services.order.list_cancel_requests(self.app.session, store_id):
            row = self.cancel_tree.insert(
                "", "end", values=(order_numbers.get(request.order_id, ""), request.reason)
            )
            self.cancel_items[row] = request

        self.modify_tree.delete(*self.modify_tree.get_children())
        self.modify_items.clear()
        for request in self.services.order.list_pending_modify_requests(self.app.session, store_id):
            row = self.modify_tree.insert(
                "",
                "end",
                values=(
                    order_numbers.get(request.order_id, ""),
                    cents_to_yuan(request.old_total_cents),
                    cents_to_yuan(request.new_total_cents),
                    request.check_in_date,
                    request.check_out_date,
                ),
            )
            self.modify_items[row] = request

    def _current(self):
        index = self.notebook.index(self.notebook.select())
        if index == 0:
            tree, items = self.price_tree, self.price_items
        elif index == 1:
            tree, items = self.cancel_tree, self.cancel_items
        else:
            tree, items = self.modify_tree, self.modify_items
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一条申请")
            return None, None
        return index, items[selection[0]]

    @guarded
    def approve(self) -> None:
        index, request = self._current()
        if request is None:
            return
        if index == 0:
            self.services.pricing.approve_price_change(self.app.session, request.id)
        elif index == 1:
            self.services.order.approve_cancel_request(self.app.session, request.id)
        else:
            self.services.order.approve_modify_request(self.app.session, request.id)
        self.refresh()

    @guarded
    def reject(self) -> None:
        index, request = self._current()
        if request is None:
            return
        if index == 0:
            self.services.pricing.reject_price_change(self.app.session, request.id)
        elif index == 1:
            self.services.order.reject_cancel_request(self.app.session, request.id)
        else:
            self.services.order.reject_modify_request(self.app.session, request.id)
        self.refresh()


class StoreStaffScreen(Screen):
    title = "本店员工"
    subtitle = "本店人员名册与账号状态"

    def build(self) -> None:
        body = theme.card(self, "员工名册", fill="both", expand=True)
        self.tree = theme.table(
            body, ("姓名", "手机号", "角色", "状态"), widths=[160, 180, 160, 140], height=14
        )
        actions = theme.actions(body)
        theme.ghost(actions, "刷新", self.refresh).pack(side="left")
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for user in self.services.account.list_staff_of_store(
            self.app.session, self.app.session.store_id
        ):
            self.tree.insert(
                "", "end", values=(user.name, user.phone, user.role.value, user.status.value)
            )


class MessageScreen(Screen):
    title = "消息中心"
    subtitle = "通知发送结果与重试情况"

    def build(self) -> None:
        body = theme.card(self, "本店通知记录", fill="both", expand=True)
        self.tree = theme.table(
            body, ("类型", "状态", "失败原因", "重试次数"), widths=[200, 120, 220, 110], height=14
        )
        actions = theme.actions(body)
        theme.ghost(actions, "刷新", self.refresh).pack(side="left")
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for note in self.services.notify.list_for_store(
            self.app.session, self.app.session.store_id
        ):
            self.tree.insert(
                "",
                "end",
                values=(note.type, note.status.value, note.failure_reason or "", note.retry_count),
            )


class AuditScreen(Screen):
    title = "操作日志"
    subtitle = "按角色数据范围过滤，日志不可修改"

    def build(self) -> None:
        body = theme.card(self, "最近操作", fill="both", expand=True)
        self.tree = theme.table(
            body,
            ("时间", "操作人角色", "动作", "对象", "原因"),
            widths=[130, 140, 220, 110, 260],
            height=14,
        )
        actions = theme.actions(body)
        theme.ghost(actions, "刷新", self.refresh).pack(side="left")
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for entry in self.services.audit.query_audit(self.app.session, limit=200):
            self.tree.insert(
                "",
                "end",
                values=(
                    entry.created_at.strftime("%m-%d %H:%M"),
                    entry.operator_role,
                    entry.action,
                    entry.object_type,
                    entry.reason or "",
                ),
            )
