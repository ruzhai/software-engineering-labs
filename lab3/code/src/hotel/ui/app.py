"""程序入口与主窗口。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from hotel.context import build_services
from hotel.core.errors import AppError
from hotel.m01_account.model import Role, Session
from hotel.ui.common import guarded


class Screen(ttk.Frame):
    title = ""

    def __init__(self, app: "App") -> None:
        super().__init__(app.body)
        self.app = app
        self.services = app.services
        self.build()

    def build(self) -> None:  # pragma: no cover - 由子类实现
        raise NotImplementedError


class App(tk.Tk):
    def __init__(self, services) -> None:
        super().__init__()
        self.title("酒店预订管理系统")
        self.geometry("1020x700")
        self.services = services
        self.session: Session | None = None
        self.search_params: dict = {}
        self.search_results: list = []
        self.selected_room_type = None
        self.current_order = None

        self.toolbar = ttk.Frame(self, padding=(8, 6))
        self.toolbar.pack(fill="x")
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)

        self.show_login()

    # ---------- 导航 ----------

    def clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

    def show(self, screen_class) -> None:
        self.clear()
        screen_class(self)

    def show_login(self) -> None:
        self.session = None
        for child in self.toolbar.winfo_children():
            child.destroy()
        self.show(LoginScreen)

    @guarded
    def after_login(self, session: Session) -> None:
        self.session = session
        for child in self.toolbar.winfo_children():
            child.destroy()
        ttk.Label(self.toolbar, text=f"{session.name}（{session.role.value}）").pack(side="left")
        ttk.Button(self.toolbar, text="退出登录", command=self.show_login).pack(side="right")

        from hotel.ui.customer import (  # pylint: disable=import-outside-toplevel
            CustomerOrdersScreen,
            QueryScreen,
        )
        from hotel.ui.frontdesk import (  # pylint: disable=import-outside-toplevel
            BoardScreen,
            CheckInScreen,
            CheckOutScreen,
        )
        from hotel.ui.manager import PricingScreen  # pylint: disable=import-outside-toplevel

        if session.role is Role.CUSTOMER:
            ttk.Button(self.toolbar, text="查询房型", command=lambda: self.show(QueryScreen)).pack(
                side="left", padx=4
            )
            ttk.Button(
                self.toolbar, text="我的订单", command=lambda: self.show(CustomerOrdersScreen)
            ).pack(side="left", padx=4)
            self.show(QueryScreen)
        elif session.role is Role.FRONT_DESK:
            ttk.Button(self.toolbar, text="房态看板", command=lambda: self.show(BoardScreen)).pack(
                side="left", padx=4
            )
            ttk.Button(
                self.toolbar, text="办理入住", command=lambda: self.show(CheckInScreen)
            ).pack(side="left", padx=4)
            ttk.Button(
                self.toolbar, text="办理退房", command=lambda: self.show(CheckOutScreen)
            ).pack(side="left", padx=4)
            self.show(BoardScreen)
        elif session.role is Role.STORE_MANAGER:
            ttk.Button(
                self.toolbar, text="改价与审批", command=lambda: self.show(PricingScreen)
            ).pack(side="left", padx=4)
            self.show(PricingScreen)
        else:
            messagebox.showinfo("提示", "片区负责人端仅提供数据服务，暂无界面。")
            self.show_login()


class LoginScreen(Screen):
    title = "登录"

    def build(self) -> None:
        box = ttk.LabelFrame(self, text="登录", padding=20)
        box.place(relx=0.5, rely=0.4, anchor="center")

        self.phone = tk.StringVar(value="13800000001")
        self.password = tk.StringVar(value="secret1")

        ttk.Label(box, text="手机号").grid(row=0, column=0, sticky="e", pady=6)
        ttk.Entry(box, textvariable=self.phone, width=24).grid(row=0, column=1, pady=6)
        ttk.Label(box, text="密码").grid(row=1, column=0, sticky="e", pady=6)
        ttk.Entry(box, textvariable=self.password, show="*", width=24).grid(row=1, column=1, pady=6)
        ttk.Button(box, text="登录", command=self.login).grid(
            row=2, column=0, columnspan=2, pady=(12, 4), sticky="ew"
        )
        ttk.Button(box, text="注册顾客账号", command=self.open_register).grid(
            row=3, column=0, columnspan=2, sticky="ew"
        )

    @guarded
    def login(self) -> None:
        session = self.services.account.login(self.phone.get(), self.password.get())
        self.app.after_login(session)

    def open_register(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("注册顾客账号")
        dialog.geometry("320x220")
        name = tk.StringVar()
        phone = tk.StringVar()
        password = tk.StringVar()
        for index, (label, variable) in enumerate(
            (("姓名", name), ("手机号", phone), ("密码", password))
        ):
            ttk.Label(dialog, text=label).grid(row=index, column=0, padx=10, pady=8, sticky="e")
            ttk.Entry(dialog, textvariable=variable, width=22).grid(
                row=index, column=1, padx=10, pady=8
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

        ttk.Button(dialog, text="注册", command=submit).grid(
            row=3, column=0, columnspan=2, pady=12, sticky="ew", padx=10
        )


def main() -> None:
    services = build_services()
    App(services).mainloop()


if __name__ == "__main__":
    main()
