#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import shlex
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

SSH_CONFIG_FILE = os.path.expanduser("~/.ssh/config")
SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 3000

ssh_process = None
current_host = None
all_ssh_hosts = []
popup_window = None
popup_listbox = None


def log(message: str):
    terminal.insert(tk.END, message)
    terminal.see(tk.END)


def get_ssh_hosts():
    hosts = []
    if not os.path.exists(SSH_CONFIG_FILE):
        messagebox.showerror("Ошибка", f"Файл {SSH_CONFIG_FILE} не найден.", parent=root)
        return hosts

    with open(SSH_CONFIG_FILE, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            match = re.match(r"^\s*Host\s+(.+)$", line)
            if not match:
                continue
            for alias in shlex.split(match.group(1), comments=False, posix=True):
                if alias != "*" and "*" not in alias and "?" not in alias:
                    hosts.append(alias)

    seen = set()
    result = []
    for host in hosts:
        if host not in seen:
            result.append(host)
            seen.add(host)
    return result


def filter_hosts():
    typed = host_combobox.get().strip().lower()
    if not typed:
        filtered = all_ssh_hosts
    else:
        filtered = [h for h in all_ssh_hosts if h.lower().startswith(typed)]
        if not filtered:
            filtered = [h for h in all_ssh_hosts if typed in h.lower()]
    host_combobox["values"] = filtered
    return filtered


def hide_suggestions():
    global popup_window
    if popup_window is not None and popup_window.winfo_exists():
        popup_window.withdraw()


def ensure_popup():
    global popup_window, popup_listbox
    if popup_window is not None and popup_window.winfo_exists():
        return

    popup_window = tk.Toplevel(root)
    popup_window.withdraw()
    popup_window.overrideredirect(True)
    popup_window.attributes("-topmost", True)
    popup_window.configure(bg="#D7E2EC")

    frame = tk.Frame(popup_window, bg="#D7E2EC", bd=1)
    frame.pack(fill="both", expand=True)

    popup_listbox = tk.Listbox(
        frame,
        height=10,
        bg="#F6F9FC",
        fg="#16324F",
        relief="flat",
        bd=0,
        highlightthickness=0,
        selectbackground="#1F6FEB",
        selectforeground="white",
        font=("Segoe UI", 11),
    )
    popup_listbox.pack(fill="both", expand=True)
    popup_listbox.bind("<Double-Button-1>", connect_selected_from_list)
    popup_listbox.bind("<Return>", connect_selected_from_list)
    popup_listbox.bind("<<ListboxSelect>>", on_popup_select)


def show_suggestions(filtered):
    ensure_popup()
    popup_listbox.delete(0, tk.END)
    for host in filtered[:14]:
        popup_listbox.insert(tk.END, host)

    if not filtered:
        hide_suggestions()
        return

    x = host_combobox.winfo_rootx()
    y = host_combobox.winfo_rooty() + host_combobox.winfo_height() + 2
    width = host_combobox.winfo_width()
    row_height = 28
    height = min(len(filtered[:14]), 14) * row_height + 4
    popup_window.geometry(f"{width}x{height}+{x}+{y}")
    popup_window.deiconify()
    popup_window.lift()

    popup_listbox.selection_clear(0, tk.END)
    popup_listbox.selection_set(0)
    popup_listbox.activate(0)


def update_suggestions(event=None):
    filtered = filter_hosts()
    typed = host_combobox.get().strip()
    if not typed:
        hide_suggestions()
        return
    show_suggestions(filtered)


def apply_host(host_alias: str):
    if not host_alias:
        return
    host_combobox.set(host_alias)
    hide_suggestions()


def connect_selected_from_list(event=None):
    selection = popup_listbox.curselection() if popup_listbox else ()
    if selection:
        apply_host(popup_listbox.get(selection[0]))
        on_connect()


def on_popup_select(event=None):
    selection = popup_listbox.curselection() if popup_listbox else ()
    if selection:
        apply_host(popup_listbox.get(selection[0]))


def on_host_enter(event=None):
    selection = popup_listbox.curselection() if popup_listbox else ()
    if selection:
        apply_host(popup_listbox.get(selection[0]))
        on_connect()
        return

    typed = host_combobox.get().strip()
    if typed in all_ssh_hosts:
        apply_host(typed)
        on_connect()
        return

    filtered = filter_hosts()
    if filtered:
        apply_host(filtered[0])
        on_connect()
    else:
        messagebox.showwarning("Не найдено", "Такого alias нет в ~/.ssh/config.", parent=root)


def on_host_down(event=None):
    filtered = filter_hosts()
    if not filtered:
        return "break"
    show_suggestions(filtered)
    popup_listbox.focus_set()
    return "break"


def on_popup_escape(event=None):
    host_combobox.focus_set()
    hide_suggestions()
    return "break"


def on_root_click(event=None):
    if popup_window is None or not popup_window.winfo_exists():
        return
    widget = event.widget
    if widget in {host_combobox, popup_listbox}:
        return
    hide_suggestions()


def get_port_listeners(port=SOCKS_PORT):
    cmd = (
        f"ss -lntp '( sport = :{port} )' 2>/dev/null "
        "| awk -F'pid=' 'NR>1 {print $2}' "
        "| awk -F',' '{print $1}'"
    )
    try:
        out = subprocess.check_output(["sh", "-lc", cmd], text=True).strip()
    except Exception:
        return []

    pids = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit() and line not in pids:
            pids.append(line)
    return pids


def free_proxy_port():
    global ssh_process, current_host

    pids = get_port_listeners(SOCKS_PORT)
    if not pids:
        log(f"ℹ️ Порт localhost:{SOCKS_PORT} уже свободен.\n")
        return

    failed = []
    for pid in pids:
        try:
            subprocess.run(["kill", "-9", pid], check=True)
            log(f"🔴 Остановил PID {pid}, который держал localhost:{SOCKS_PORT}.\n")
        except Exception:
            failed.append(pid)

    time.sleep(0.3)
    remaining = get_port_listeners(SOCKS_PORT)
    if remaining:
        messagebox.showwarning(
            "Порт не полностью освобожден",
            f"После очистки localhost:{SOCKS_PORT} всё ещё занят PID: {', '.join(remaining)}",
            parent=root,
        )
        log(f"⚠️ Порт {SOCKS_PORT} всё ещё занят PID: {', '.join(remaining)}.\n")
    elif failed:
        messagebox.showwarning(
            "Не всё завершилось",
            f"Не удалось остановить PID: {', '.join(failed)}",
            parent=root,
        )
    else:
        log(f"✅ Порт localhost:{SOCKS_PORT} освобожден.\n")

    if ssh_process and ssh_process.poll() is None:
        ssh_process = None
    current_host = None
    status_label.config(text="Не подключено", fg="#5B6B7A")


def chromium_proxy_running():
    patterns = [
        f"--proxy-server=socks5://localhost:{SOCKS_PORT}",
        f"--proxy-server=socks5://127.0.0.1:{SOCKS_PORT}",
        f"--proxy-server=socks5h://localhost:{SOCKS_PORT}",
        f"--proxy-server=socks5h://127.0.0.1:{SOCKS_PORT}",
    ]
    try:
        out = subprocess.check_output(
            ["sh", "-lc", "pgrep -af 'chromium|chrome' || true"],
            text=True,
        )
    except Exception:
        return False
    return any(pattern in out for pattern in patterns)


def launch_chromium_proxy():
    if chromium_proxy_running():
        log("✅ Chromium уже запущен через proxy localhost:3000.\n")
        return

    try:
        subprocess.Popen(["chromium", f"--proxy-server=socks5://localhost:{SOCKS_PORT}"])
        log("🚀 Запустил Chromium через proxy localhost:3000.\n")
    except FileNotFoundError:
        messagebox.showerror(
            "Chromium не найден",
            "Команда chromium не найдена. Установи Chromium или поправь имя команды в скрипте.",
            parent=root,
        )
        log("❌ Команда chromium не найдена.\n")
    except Exception as exc:
        messagebox.showerror("Ошибка запуска", f"Не удалось запустить Chromium:\n{exc}", parent=root)
        log(f"❌ Ошибка запуска Chromium: {exc}\n")


def read_ssh_stderr(proc):
    while proc and proc.poll() is None:
        line = proc.stderr.readline()
        if not line:
            time.sleep(0.2)
            continue
        log(f"[ssh] {line}")


def start_ssh_proxy(host_alias: str):
    global ssh_process, current_host

    listeners = get_port_listeners(SOCKS_PORT)
    if listeners:
        messagebox.showerror(
            "Порт занят",
            f"Порт localhost:{SOCKS_PORT} уже занят PID: {', '.join(listeners)}.\n"
            "Отключи старый прокси или закрой процесс вручную.",
            parent=root,
        )
        log(f"❌ Порт {SOCKS_PORT} занят PID: {', '.join(listeners)}. Новое подключение не запущено.\n")
        return

    cmd = [
        "ssh",
        "-T",
        "-N",
        "-o", "RequestTTY=no",
        "-o", "RemoteCommand=none",
        "-o", "StrictHostKeyChecking=no",
        "-D", f"{SOCKS_HOST}:{SOCKS_PORT}",
        host_alias,
    ]

    def runner():
        global ssh_process, current_host
        try:
            log(f"⏳ Подключаюсь к {host_alias}, SOCKS5 {SOCKS_HOST}:{SOCKS_PORT}...\n")
            ssh_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            threading.Thread(target=read_ssh_stderr, args=(ssh_process,), daemon=True).start()

            time.sleep(2)
            if ssh_process.poll() is None:
                current_host = host_alias
                status_label.config(text=f"Подключено: {host_alias}", fg="#0B6B3A")
                log("✅ SSH-прокси поднят.\n")
                launch_chromium_proxy()
            else:
                err = ssh_process.stderr.read() if ssh_process.stderr else ""
                ssh_process = None
                current_host = None
                status_label.config(text="Не подключено", fg="#B42318")
                log(f"❌ SSH завершился сразу:\n{err}\n")
        except Exception as exc:
            ssh_process = None
            current_host = None
            status_label.config(text="Ошибка подключения", fg="#B42318")
            log(f"❌ Ошибка подключения: {exc}\n")

    threading.Thread(target=runner, daemon=True).start()


def on_connect():
    host_alias = host_combobox.get().strip()
    if not host_alias:
        messagebox.showerror("Ошибка", "Выбери сервер из ~/.ssh/config.", parent=root)
        return

    if host_alias not in all_ssh_hosts:
        filtered = filter_hosts()
        if filtered:
            host_alias = filtered[0]
            apply_host(host_alias)
        else:
            messagebox.showerror("Ошибка", "Такой сервер не найден в ~/.ssh/config.", parent=root)
            return

    if ssh_process and ssh_process.poll() is None and current_host == host_alias:
        log(f"ℹ️ Уже подключено к {host_alias}.\n")
        launch_chromium_proxy()
        return

    if ssh_process and ssh_process.poll() is None and current_host != host_alias:
        log(f"🔄 Переключаю прокси с {current_host} на {host_alias}...\n")
        disconnect()
        time.sleep(0.5)

    start_ssh_proxy(host_alias)


def disconnect():
    global ssh_process, current_host

    if ssh_process and ssh_process.poll() is None:
        log("🔧 Отключаю SSH-прокси...\n")
        ssh_process.terminate()
        time.sleep(0.8)
        if ssh_process.poll() is None:
            ssh_process.kill()
        log("🔴 SSH-прокси остановлен.\n")
    else:
        log("ℹ️ Активного подключения этой программы нет.\n")

    ssh_process = None
    current_host = None
    status_label.config(text="Не подключено", fg="#5B6B7A")


root = tk.Tk()
root.title("SSHProxy Lite")
root.geometry("680x430")
root.configure(bg="#EEF3F8")

BG_APP = "#EEF3F8"
BG_PANEL = "#FFFFFF"
BG_SUBTLE = "#F6F9FC"
TEXT_MAIN = "#16324F"
TEXT_MUTED = "#5B6B7A"
ACCENT = "#1F6FEB"

style = ttk.Style()
try:
    style.theme_use("clam")
except Exception:
    pass
style.configure("TCombobox", fieldbackground="#FFFFFF", background="#FFFFFF")

all_ssh_hosts = get_ssh_hosts()

header = tk.Frame(root, bg=BG_APP)
header.pack(fill="x", padx=12, pady=(10, 6))

tk.Label(
    header,
    text="SSHProxy Lite",
    font=("Segoe UI", 18, "bold"),
    bg=BG_APP,
    fg=TEXT_MAIN,
).pack(side="left")

status_label = tk.Label(
    header,
    text="Не подключено",
    font=("Segoe UI", 10, "bold"),
    bg=BG_APP,
    fg=TEXT_MUTED,
)
status_label.pack(side="right")

server_block = tk.LabelFrame(
    root,
    text="Сервер из ~/.ssh/config",
    padx=12,
    pady=10,
    bg=BG_PANEL,
    fg=TEXT_MAIN,
    font=("Segoe UI", 10, "bold"),
    bd=1,
    relief="solid",
)
server_block.pack(fill="x", padx=12, pady=(0, 8))

tk.Label(
    server_block,
    text="Начни вводить alias. Список открывается поверх окна, Enter сразу подключает.",
    bg=BG_PANEL,
    fg=TEXT_MUTED,
    font=("Segoe UI", 10),
).pack(anchor="w")

host_combobox = ttk.Combobox(server_block, values=all_ssh_hosts, width=60)
host_combobox.pack(fill="x", pady=(5, 0))
host_combobox.bind("<KeyRelease>", update_suggestions)
host_combobox.bind("<Return>", on_host_enter)
host_combobox.bind("<Down>", on_host_down)
host_combobox.bind("<<ComboboxSelected>>", lambda event: apply_host(host_combobox.get().strip()))

actions = tk.Frame(root, bg=BG_APP)
actions.pack(fill="x", padx=12, pady=(0, 8))

connect_button = tk.Button(
    actions,
    text="Подключиться + Chromium",
    command=on_connect,
    bg="#16A34A",
    fg="white",
    activebackground="#15803D",
    activeforeground="white",
    font=("Segoe UI", 11, "bold"),
    padx=16,
    pady=8,
)
connect_button.pack(side="left", padx=(0, 8))

disconnect_button = tk.Button(
    actions,
    text="Отключиться",
    command=disconnect,
    bg="#DC2626",
    fg="white",
    activebackground="#B91C1C",
    activeforeground="white",
    font=("Segoe UI", 11, "bold"),
    padx=16,
    pady=8,
)
disconnect_button.pack(side="left")

free_port_button = tk.Button(
    actions,
    text="Освободить localhost:3000",
    command=free_proxy_port,
    bg="#2563EB",
    fg="white",
    activebackground="#1D4ED8",
    activeforeground="white",
    font=("Segoe UI", 11, "bold"),
    padx=16,
    pady=8,
)
free_port_button.pack(side="left", padx=(8, 0))

terminal_block = tk.LabelFrame(root, text="Лог", padx=10, pady=8)
terminal_block.pack(fill="both", expand=True, padx=12, pady=(0, 12))

terminal = tk.Text(
    terminal_block,
    height=12,
    bg="#F8FBFE",
    fg=TEXT_MAIN,
    insertbackground=TEXT_MAIN,
    relief="solid",
    bd=1,
    highlightthickness=0,
    font=("Consolas", 10),
)
terminal.pack(fill="both", expand=True)

root.bind_all("<Button-1>", on_root_click, add="+")
ensure_popup()
popup_listbox.bind("<Escape>", on_popup_escape)

log("Готово.\n")
log("Введите alias, например sky, и нажмите Enter для подключения.\n")
log("Кнопка подключения поднимает SSH-прокси и при необходимости запускает Chromium через localhost:3000.\n\n")

root.mainloop()
