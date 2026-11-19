"""程序入口与主窗口。

布局沿用实验二的桌面端：左侧导航、顶部标题栏、右侧内容区。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from hotel.context import build_services
from hotel.core.errors import AppError
from hotel.m01_account.model import Role, Session
from hotel.ui import theme
from hotel.ui.common import guarded

ROLE_LABEL = {
    Role.CUSTOMER: "顾客",
    Role.FRONT_DESK: "前台",
    Role.STORE_MANAGER: "店长",
    Role.AREA_MANAGER: "片区负责人",
}


class Screen(tk.Frame):
    title = ""
    subtitle = ""

    def __init__(self, app: "App") -> None:
        super().__init__(app.content, bg=theme.BG)
        self.pack(fill="both", expand=True)
        self.app = app
        self.services = app.services
        self.build()

    def build(self) -> None:  # pragma: no cover - 由子类实现
        raise NotImplementedError


def nav_items(role: Role) -> list[tuple[str, type]]:
    from hotel.ui import (  # pylint: disable=import-outside-toplevel
        customer,
        customer_extra,
        frontdesk,
        frontdesk_extra,
        manager,
        manager_extra,
        platform,
    )

    if role is Role.CUSTOMER:
        return [
            ("找酒店", customer.QueryScreen),
            ("我的订单", customer.CustomerOrdersScreen),
            ("提交评价", customer_extra.ReviewScreen),
        ]
    if role is Role.FRONT_DESK:
        return [
            ("房态看板", frontdesk.BoardScreen),
            ("办理入住", frontdesk.CheckInScreen),
            ("办理退房", frontdesk.CheckOutScreen),
            ("客房打扫", frontdesk_extra.HousekeepingScreen),
            ("前台开单", frontdesk_extra.WalkInScreen),
            ("消息中心", manager_extra.MessageScreen),
        ]
    if role is Role.STORE_MANAGER:
        return [
            ("改价与审批", manager.PricingScreen),
            ("审批中心", manager_extra.ApprovalScreen),
            ("本店员工", manager_extra.StoreStaffScreen),
            ("消息中心", manager_extra.MessageScreen),
            ("操作日志", manager_extra.AuditScreen),
        ]
    return [
        ("片区概览", platform.RegionScreen),
        ("价格区间", platform.PriceRangeScreen),
        ("店长名册", platform.RosterScreen),
        ("操作日志", manager_extra.AuditScreen),
    ]


class App(tk.Tk):
    def __init__(self, services) -> None:
        super().__init__()
        self.title("酒店预订管理系统")
        self.geometry("1180x760")
        self.minsize(1040, 700)
        self.configure(bg=theme.BG)
        theme.setup(self)

        self.services = services
        self.session: Session | None = None
        self.nav_buttons: dict[type, tk.Button] = {}
        self.search_params: dict = {}
        self.search_results: list = []
        self.selected_room_type = None
        self.current_order = None

        self.sidebar = tk.Frame(self, bg=theme.SURFACE, width=216)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.nav_container = tk.Frame(self.sidebar, bg=theme.SURFACE)
        self.footer = tk.Frame(self.sidebar, bg=theme.SURFACE)

        self.main = tk.Frame(self, bg=theme.BG)
        self.main.pack(side="left", fill="both", expand=True)

        self.header = tk.Frame(self.main, bg=theme.SURFACE, height=78)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.content = tk.Frame(self.main, bg=theme.BG)
        self.content.pack(fill="both", expand=True, padx=22, pady=18)

        self.show_login()

    # ---------- 侧边栏 ----------

    def build_sidebar(self) -> None:
        for child in self.sidebar.winfo_children():
            child.destroy()

        brand = tk.Frame(self.sidebar, bg=theme.SURFACE)
        brand.pack(fill="x", padx=18, pady=(20, 16))
        tk.Label(
            brand,
            text="酒",
            bg=theme.ACCENT,
            fg="#FFFFFF",
            font=(theme.FAMILY, 12, "bold"),
            width=2,
            pady=4,
        ).pack(side="left")
        titles = tk.Frame(brand, bg=theme.SURFACE)
        titles.pack(side="left", padx=10)
        tk.Label(
            titles, text="酒店预订", bg=theme.SURFACE, fg=theme.TEXT, font=theme.FONT_BRAND
        ).pack(anchor="w")
        tk.Label(
            titles, text="管理系统", bg=theme.SURFACE, fg=theme.MUTED, font=theme.FONT_SMALL
        ).pack(anchor="w")

        self.nav_container = tk.Frame(self.sidebar, bg=theme.SURFACE)
        self.nav_container.pack(fill="both", expand=True, padx=8, pady=4)

        self.footer = tk.Frame(self.sidebar, bg=theme.SURFACE)
        self.footer.pack(fill="x", padx=18, pady=16)

    def set_nav(self, items: list[tuple[str, type]]) -> None:
        self.nav_buttons = {}
        for label, screen_class in items:
            button = tk.Button(
                self.nav_container,
                text=label,
                anchor="w",
                padx=14,
                pady=9,
                bd=0,
                relief="flat",
                bg=theme.SURFACE,
                fg=theme.TEXT,
                activebackground=theme.ACCENT_SOFT,
                activeforeground=theme.ACCENT,
                font=theme.FONT_NAV,
                cursor="hand2",
                command=lambda screen_class=screen_class: self.show(screen_class),
            )
            button.pack(fill="x", pady=1)
            self.nav_buttons[screen_class] = button

    def mark_active(self, screen_class: type) -> None:
        for cls, button in self.nav_buttons.items():
            active = cls is screen_class
            button.configure(
                bg=theme.ACCENT_SOFT if active else theme.SURFACE,
                fg=theme.ACCENT if active else theme.TEXT,
                font=(theme.FAMILY, 10, "bold") if active else theme.FONT_NAV,
            )

    def build_footer(self) -> None:
        for child in self.footer.winfo_children():
            child.destroy()
        if self.session is None:
            return
        tk.Label(
            self.footer,
            text=self.session.name,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=theme.FONT_BODY,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            self.footer,
            text=ROLE_LABEL[self.session.role],
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
            anchor="w",
        ).pack(fill="x", pady=(2, 8))
        ttk.Button(
            self.footer, text="退出登录", command=self.show_login, style="Ghost.TButton"
        ).pack(fill="x")

    # ---------- 顶部与内容 ----------

    def set_header(self, title: str, subtitle: str) -> None:
        for child in self.header.winfo_children():
            child.destroy()
        left = tk.Frame(self.header, bg=theme.SURFACE)
        left.pack(side="left", padx=24)
        tk.Label(left, text=title, bg=theme.SURFACE, fg=theme.TEXT, font=theme.FONT_TITLE).pack(
            anchor="w"
        )
        if subtitle:
            tk.Label(
                left, text=subtitle, bg=theme.SURFACE, fg=theme.MUTED, font=theme.FONT_SMALL
            ).pack(anchor="w")

        if self.session is not None:
            right = tk.Frame(self.header, bg=theme.SURFACE)
            right.pack(side="right", padx=24)
            tk.Label(
                right,
                text="班中",
                bg=theme.SUCCESS_SOFT,
                fg=theme.SUCCESS,
                font=theme.FONT_SMALL,
                padx=10,
                pady=3,
            ).pack(side="left", padx=(0, 10))
            tk.Label(
                right,
                text=self.session.name,
                bg=theme.SURFACE,
                fg=theme.TEXT,
                font=theme.FONT_BODY,
            ).pack(side="left")

    def show(self, screen_class: type) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        self.mark_active(screen_class)
        self.set_header(screen_class.title, getattr(screen_class, "subtitle", ""))
        screen_class(self)

    # ---------- 登录 ----------

    def show_login(self) -> None:
        self.session = None
        self.build_sidebar()
        self.set_nav([])
        self.build_footer()
        self.show(LoginScreen)

    @guarded
    def after_login(self, session: Session) -> None:
        self.session = session
        self.build_sidebar()
        items = nav_items(session.role)
        self.set_nav(items)
        self.build_footer()
        self.show(items[0][1])


class LoginScreen(Screen):
    title = "登录"
    subtitle = "先选身份，再登录对应账号"

    ROLE_ACCOUNTS = (
        (Role.CUSTOMER, "顾客", "13800000001"),
        (Role.FRONT_DESK, "前台", "13900000003"),
        (Role.STORE_MANAGER, "店长", "13900000002"),
        (Role.AREA_MANAGER, "片区负责人", "13900000001"),
    )

    def build(self) -> None:
        holder = tk.Frame(self, bg=theme.BG)
        holder.place(relx=0.5, rely=0.46, anchor="center")

        box = tk.Frame(
            holder, bg=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1
        )
        box.pack()
        inner = tk.Frame(box, bg=theme.SURFACE)
        inner.pack(padx=44, pady=32)

        tk.Label(
            inner,
            text="酒店预订管理系统",
            bg=theme.SURFACE,
            fg=theme.TEXT,
            font=(theme.FAMILY, 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            inner,
            text="四类角色共用同一入口，请先选择身份",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=theme.FONT_SMALL,
        ).pack(anchor="w", pady=(4, 18))

        theme.field_label(inner, "登录身份").pack(anchor="w")
        role_row = tk.Frame(inner, bg=theme.SURFACE)
        role_row.pack(fill="x", pady=(6, 16))
        self.role_var: Role = Role.CUSTOMER
        self.role_buttons: dict[Role, tk.Button] = {}
        for role, label, phone in self.ROLE_ACCOUNTS:
            button = tk.Button(
                role_row,
                text=label,
                bd=0,
                relief="flat",
                padx=12,
                pady=7,
                font=theme.FONT_BODY,
                cursor="hand2",
                command=lambda role=role, phone=phone: self._select_role(role, phone),
            )
            button.pack(side="left", padx=(0, 8))
            self.role_buttons[role] = button

        self.phone = tk.StringVar()
        self.password = tk.StringVar(value="secret1")
        theme.field_label(inner, "手机号").pack(anchor="w")
        theme.entry(inner, self.phone, width=30).pack(fill="x", pady=(4, 12))
        theme.field_label(inner, "密码").pack(anchor="w")
        ttk.Entry(inner, textvariable=self.password, show="*", width=30, style="App.TEntry").pack(
            fill="x", pady=(4, 18)
        )

        theme.primary(inner, "登录", self.login).pack(fill="x")
        theme.ghost(inner, "注册顾客账号", self.open_register).pack(fill="x", pady=(8, 0))

        self._select_role(Role.CUSTOMER, "13800000001")

    def _select_role(self, role: Role, phone: str) -> None:
        self.role_var = role
        self.phone.set(phone)
        for item_role, button in self.role_buttons.items():
            active = item_role is role
            button.configure(
                bg=theme.ACCENT if active else theme.SURFACE_ALT,
                fg="#FFFFFF" if active else theme.TEXT,
                activebackground=theme.ACCENT if active else theme.BORDER,
                activeforeground="#FFFFFF" if active else theme.TEXT,
            )

    @guarded
    def login(self) -> None:
        session = self.services.account.login(self.phone.get(), self.password.get())
        if session.role is not self.role_var:
            messagebox.showwarning(
                "身份不匹配",
                f"这个账号是「{ROLE_LABEL[session.role]}」，请选择对应身份登录",
            )
            return
        self.app.after_login(session)

    def open_register(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("注册顾客账号")
        dialog.configure(bg=theme.BG)
        dialog.geometry("380x320")
        dialog.attributes("-topmost", True)

        card = theme.card(dialog, "注册顾客账号", fill="both", expand=True, padx=16, pady=16)
        name = tk.StringVar()
        phone = tk.StringVar()
        password = tk.StringVar()
        for label, variable, show in (
            ("姓名", name, ""),
            ("手机号", phone, ""),
            ("密码", password, "*"),
        ):
            theme.field_label(card, label).pack(anchor="w", pady=(6, 2))
            ttk.Entry(card, textvariable=variable, width=28, show=show, style="App.TEntry").pack(
                fill="x"
            )

        @guarded
        def submit() -> None:
            try:
                self.services.account.register_customer(name.get(), phone.get(), password.get())
            except AppError as exc:
                messagebox.showwarning("注册未完成", exc.message)
                return
            messagebox.showinfo("注册成功", "账号已创建，可以直接登录")
            dialog.destroy()

        theme.primary(card, "注册", submit).pack(fill="x", pady=(18, 0))


def main() -> None:
    services = build_services()
    App(services).mainloop()


if __name__ == "__main__":
    main()
