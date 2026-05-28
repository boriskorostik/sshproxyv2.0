#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import subprocess
import threading
import time
import ipaddress
import pandas as pd
import requests
import sys

# =========================
#  Запуск module.py
# =========================

def open_panel_config():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        module_path = os.path.join(current_dir, "module.py")
        subprocess.run([sys.executable, module_path], check=True)
    except subprocess.CalledProcessError as e:
        messagebox.showerror("Ошибка запуска", f"Модуль завершился с ошибкой:\n{e}", parent=root)
    except FileNotFoundError:
        messagebox.showerror("Файл не найден", "module.py не найден рядом с программой.", parent=root)


# =========================
#  Paths / globals
# =========================

SSH_CONFIG_FILE = os.path.expanduser("~/.ssh/config")
CONFIG_DIR = os.path.expanduser("/opt/sshgui")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.xlsx")

ssh_process = None
chromium_process = None

ALL_SSH_HOSTS = []
CURRENT_OBJECT = ""
CURRENT_HOST = None  # активный выбранный host для remote ping/arp

# =========================
#  Log helper
# =========================

def log(msg: str):
    terminal.insert(tk.END, msg)
    terminal.see(tk.END)


# =========================
#  IP helpers
# =========================

def socks_available():
    try:
        import socks  # noqa: F401
        return True
    except Exception:
        return False

def get_public_ip(proxy=False):
    try:
        proxies = None
        if proxy:
            proxies = {
                "http":  "socks5h://127.0.0.1:3000",
                "https": "socks5h://127.0.0.1:3000",
            }
        r = requests.get("https://api64.ipify.org?format=text", proxies=proxies, timeout=8)
        r.raise_for_status()
        return r.text.strip()
    except Exception as e:
        # Пишем причину в лог — очень помогает в диагностике
        try:
            log(f"⚠️ Ошибка IP {'через прокси' if proxy else 'напрямую'}: {repr(e)}\n")
        except Exception:
            pass
        return "Ошибка получения IP"

def update_ip_labels():
    current_ip = get_public_ip(proxy=False)
    current_ip_label.config(text=f"Текущий IP: {current_ip}", fg="#1E4DB7")

def check_proxy_ip():
    if not socks_available():
        proxy_ip_label.config(text="IP через прокси: PySocks не установлен", fg="#B42318")
        return

    # несколько попыток — ssh -D может подняться не сразу
    for _ in range(5):
        proxy_ip = get_public_ip(proxy=True)
        if proxy_ip != "Ошибка получения IP":
            proxy_ip_label.config(text=f"IP через прокси: {proxy_ip}", fg="#137A2A")
            return
        time.sleep(1)

    proxy_ip_label.config(text="IP через прокси: Ошибка получения IP", fg="#B42318")


# =========================
#  Config (xlsx)
# =========================

def check_and_create_config():
    if not os.path.exists(CONFIG_DIR):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
        except PermissionError:
            messagebox.showerror(
                "Нет прав",
                f"Нет прав на создание {CONFIG_DIR}.\n"
                "Запусти программу с sudo или измени путь CONFIG_DIR.",
                parent=root
            )
            return

    if not os.path.exists(CONFIG_FILE):
        df = pd.DataFrame(columns=["Объект", "Имя", "IP"])
        df.to_excel(CONFIG_FILE, index=False)

def load_ip_addresses():
    check_and_create_config()
    if not os.path.exists(CONFIG_FILE):
        return {}

    df = pd.read_excel(CONFIG_FILE, dtype=str, engine="openpyxl")
    ip_addresses = {}
    for _, row in df.iterrows():
        obj = (row.get("Объект") or "").strip()
        name = (row.get("Имя") or "").strip()
        ip = (row.get("IP") or "").strip()
        if not obj or not name or not ip:
            continue
        ip_addresses.setdefault(obj, {})
        ip_addresses[obj][name] = ip
    return ip_addresses


def validate_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def append_ip_address(obj: str, name: str, ip: str):
    check_and_create_config()

    if os.path.exists(CONFIG_FILE):
        df = pd.read_excel(CONFIG_FILE, dtype=str, engine="openpyxl")
    else:
        df = pd.DataFrame(columns=["Объект", "Имя", "IP"])

    if df.empty:
        df = pd.DataFrame(columns=["Объект", "Имя", "IP"])

    for col in ["Объект", "Имя", "IP"]:
        if col not in df.columns:
            df[col] = ""

    df = df[["Объект", "Имя", "IP"]].fillna("")

    mask = (
        df["Объект"].astype(str).str.strip().eq(obj) &
        df["Имя"].astype(str).str.strip().eq(name)
    )

    if mask.any():
        df.loc[mask, "IP"] = ip
    else:
        df.loc[len(df)] = [obj, name, ip]

    df.to_excel(CONFIG_FILE, index=False)


def refresh_ip_addresses(selected_ip="", selected_name=""):
    global ip_addresses
    ip_addresses = load_ip_addresses()
    update_ip_list_by_selected_host()

    if CURRENT_OBJECT and CURRENT_OBJECT in ip_addresses:
        values = [f"{name} - {addr}" for name, addr in ip_addresses[CURRENT_OBJECT].items()]
        ip_combobox["values"] = values
        if selected_ip:
            combo_value = f"{selected_name} - {selected_ip}" if selected_name else selected_ip
            if combo_value in values:
                ip_combobox.set(combo_value)


def save_current_ip():
    selected_ip = get_selected_ip()
    if not selected_ip:
        messagebox.showerror("Ошибка", "Сначала укажи IP для сохранения.", parent=root)
        return

    if not validate_ip(selected_ip):
        messagebox.showerror("Ошибка", "Введён некорректный IP-адрес.", parent=root)
        return

    obj = CURRENT_OBJECT.strip() if CURRENT_OBJECT else ""
    if not obj:
        host_name = host_combobox.get().strip()
        obj = host_name if host_name else "manual"

    device_name = simpledialog.askstring(
        "Сохранить IP",
        f"Введите название для IP {selected_ip}.\nОбъект: {obj}",
        parent=root
    )
    if device_name is None:
        return

    device_name = device_name.strip()
    if not device_name:
        messagebox.showerror("Ошибка", "Название объекта не должно быть пустым.", parent=root)
        return

    try:
        append_ip_address(obj, device_name, selected_ip)
        refresh_ip_addresses(selected_ip=selected_ip, selected_name=device_name)
        log(f"💾 Сохранено: объект '{obj}', имя '{device_name}', IP {selected_ip}\n")
        messagebox.showinfo(
            "Сохранено",
            f"IP {selected_ip} сохранён как '{device_name}' в объект '{obj}'.",
            parent=root
        )
    except PermissionError:
        messagebox.showerror(
            "Нет прав",
            f"Нет прав на запись в {CONFIG_FILE}.",
            parent=root
        )
    except Exception as e:
        messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить IP:\n{e}", parent=root)


# =========================
#  SSH config parsing
# =========================

def get_ssh_hosts():
    hosts = []
    if not os.path.exists(SSH_CONFIG_FILE):
        messagebox.showerror("Ошибка", f"Файл конфигурации {SSH_CONFIG_FILE} не найден.", parent=root)
        return hosts

    with open(SSH_CONFIG_FILE, "r") as f:
        for line in f:
            match = re.match(r"^\s*Host\s+(.+)$", line)
            if match:
                parts = match.group(1).strip().split()
                for alias in parts:
                    if alias != "*" and "?" not in alias and "*" not in alias:
                        hosts.append(alias)

    seen = set()
    uniq = []
    for h in hosts:
        if h not in seen:
            uniq.append(h)
            seen.add(h)
    return uniq


# =========================
#  UI helpers
# =========================

def get_selected_ip():
    combo = ip_combobox.get().strip()
    if combo:
        if " - " in combo:
            return combo.split(" - ", 1)[1].strip()
        return combo

    ip = ip_entry.get().strip()
    if ip:
        return ip

    return ""


# =========================
#  Host -> объект (авто)
# =========================

def resolve_object_for_host(host_alias: str) -> str:
    if not host_alias:
        return ""

    h = host_alias.strip()
    if h in ip_addresses:
        return h

    h_low = h.lower()
    best = ""
    for obj in ip_addresses.keys():
        o_low = obj.lower()
        if h_low == o_low:
            return obj
        if (o_low in h_low) or (h_low in o_low) or h_low.startswith(o_low):
            if len(obj) > len(best):
                best = obj
    return best

def update_ip_list_by_selected_host(event=None):
    global CURRENT_OBJECT

    selected_host = host_combobox.get().strip()
    if not selected_host:
        CURRENT_OBJECT = ""
        selected_object_label.config(text="Объект: —", fg="#6B7280")
        ip_combobox["values"] = []
        ip_combobox.set("")
        return

    obj = resolve_object_for_host(selected_host)
    CURRENT_OBJECT = obj

    if not obj:
        selected_object_label.config(text="Объект: не найден", fg="#B42318")
        ip_combobox["values"] = []
        ip_combobox.set("")
        ip_entry.delete(0, tk.END)
        return

    selected_object_label.config(text=f"Объект: {obj}", fg="#0B6B3A")
    values = [f"{name} - {ip}" for name, ip in ip_addresses[obj].items()]
    ip_combobox["values"] = values
    ip_combobox.set("")
    ip_combobox.config(state="readonly")


# =========================
#  Поиск по серверам (type-to-filter)
# =========================

def filter_hosts_list():
    typed = host_combobox.get().strip().lower()
    if not typed:
        filtered = ALL_SSH_HOSTS
    else:
        filtered = [h for h in ALL_SSH_HOSTS if h.lower().startswith(typed)]
        if not filtered:
            filtered = [h for h in ALL_SSH_HOSTS if typed in h.lower()]

    host_combobox["values"] = filtered
    return filtered


def update_hosts_suggestions(event=None):
    filtered = filter_hosts_list()
    typed = host_combobox.get().strip()

    hosts_listbox.delete(0, tk.END)
    if not typed:
        hosts_listbox.pack_forget()
        return

    for host in filtered[:12]:
        hosts_listbox.insert(tk.END, host)

    if filtered:
        hosts_listbox.pack(fill="x", pady=(4, 0))
    else:
        hosts_listbox.pack_forget()


def apply_selected_host(host_alias: str):
    if not host_alias:
        return

    host_combobox.set(host_alias)
    hosts_listbox.pack_forget()
    update_ip_list_by_selected_host()


def on_host_suggestion_click(event=None):
    selection = hosts_listbox.curselection()
    if not selection:
        return
    apply_selected_host(hosts_listbox.get(selection[0]))

def on_host_keyrelease(event):
    update_hosts_suggestions()

def on_host_enter(event):
    selection = hosts_listbox.curselection()
    if selection:
        apply_selected_host(hosts_listbox.get(selection[0]))
        return

    filtered = filter_hosts_list()
    if filtered:
        apply_selected_host(filtered[0])
    else:
        update_ip_list_by_selected_host()


# =========================
#  Remote command helper (for remote ping/arp)
# =========================

def run_remote_cmd(host: str, cmd: str, timeout=30):
    """
    Выполнить команду на удалённом сервере через ssh.
    Важно: отключаем RemoteCommand из ~/.ssh/config, иначе будет
    'Cannot execute command-line and remote command.'
    """
    ssh_cmd = [
        "ssh",
        "-T",
        "-o", "RequestTTY=no",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "RemoteCommand=none",   # <-- фикс
        host,
        "bash", "-lc", cmd
    ]
    return subprocess.run(
        ssh_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout
    )


# =========================
#  Process / port management
# =========================

def get_pids_listening_port(port=3000):
    cmd = f"ss -lntp '( sport = :{port} )' 2>/dev/null | awk -F'pid=' 'NR>1 {{print $2}}' | awk -F',' '{{print $1}}'"
    try:
        out = subprocess.check_output(["sh", "-lc", cmd], text=True).strip()
        if not out:
            return []
        return [p for p in out.splitlines() if p.isdigit()]
    except Exception:
        return []

def kill_pids(pids):
    for pid in pids:
        try:
            subprocess.run(["kill", "-9", pid], check=False)
            log(f"🔴 Убит процесс PID {pid}\n")
        except Exception as e:
            log(f"⚠️ Не удалось убить PID {pid}: {e}\n")

def ensure_proxy_port_free(port=3000):
    pids = get_pids_listening_port(port)
    if pids:
        log(f"⚠️ Порт {port} занят процессами: {', '.join(pids)}\n")
        log("🔧 Освобождаю порт (kill -9 владельцев)...\n")
        kill_pids(pids)

def show_active_ssh():
    try:
        cmd = r"ps -ef | grep '[s]sh' | grep -E '\-D (127\.0\.0\.1|localhost):3000' || true"
        out = subprocess.check_output(["sh", "-lc", cmd], text=True).strip()
        log("🧾 Активные SSH процессы (прокси на 3000):\n")
        log((out + "\n") if out else "— нет —\n")
    except Exception as e:
        log(f"⚠️ Ошибка получения списка ssh: {e}\n")

def kill_proxy_3000():
    ensure_proxy_port_free(3000)

def close_existing_connections():
    """
    Важно: мы сознательно закрываем chromium, который запускала программа (chromium_process).
    Если хочешь закрывать ВСЕ окна Chromium в системе — замени на pkill chromium, но это агрессивно.
    """
    global ssh_process, chromium_process

    log("🔧 Закрываю предыдущие соединения...\n")
    ensure_proxy_port_free(3000)

    if ssh_process and ssh_process.poll() is None:
        try:
            ssh_process.terminate()
            time.sleep(1)
            if ssh_process.poll() is None:
                ssh_process.kill()
            log("🔴 SSH-прокси остановлен.\n")
        except Exception as e:
            log(f"⚠️ Ошибка остановки ssh_process: {e}\n")
    ssh_process = None

    if chromium_process and chromium_process.poll() is None:
        try:
            chromium_process.terminate()
            time.sleep(1)
            if chromium_process.poll() is None:
                chromium_process.kill()
            log("🔴 Chromium (открытый программой) закрыт.\n")
        except Exception as e:
            log(f"⚠️ Ошибка остановки chromium_process: {e}\n")
    chromium_process = None


# =========================
#  Network tools (REMOTE by default if connected)
# =========================

def ping_ip():
    ip = get_selected_ip()
    if not ip:
        log("⚠️ Не указан IP-адрес для пинга.\n")
        return

    def do_ping():
        if CURRENT_HOST:
            log(f"📡 Remote ping: {CURRENT_HOST} -> {ip}...\n")
            try:
                res = run_remote_cmd(CURRENT_HOST, f"ping -c 4 -W 2 {ip}", timeout=20)
                if res.returncode == 0:
                    log(res.stdout + "\n")
                else:
                    log(f"❌ Remote ping не прошёл:\n{res.stderr or res.stdout}\n")
            except Exception as e:
                log(f"⚠️ Ошибка remote ping: {e}\n")
            return

        # fallback local
        log(f"📡 Local ping {ip}...\n")
        try:
            res = subprocess.run(["ping", "-c", "4", "-W", "2", ip],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0:
                log(res.stdout + "\n")
            else:
                log(f"❌ Пинг не прошёл:\n{res.stderr or res.stdout}\n")
        except Exception as e:
            log(f"⚠️ Ошибка запуска ping: {e}\n")

    threading.Thread(target=do_ping, daemon=True).start()

def arp_scan():
    def do_arp_scan():
        if not CURRENT_HOST:
            log("⚠️ Нет активного подключения. ARP Scan выполню на удалёнке только после подключения.\n")
            return

        log(f"📡 Remote ARP Scan на {CURRENT_HOST}...\n")

        # интерфейс на удалёнке по default route
        try:
            iface_res = run_remote_cmd(CURRENT_HOST, "ip route | awk '/^default/ {print $5; exit}'", timeout=10)
            iface = iface_res.stdout.strip()
            if not iface:
                iface_res2 = run_remote_cmd(CURRENT_HOST, "ip -o link show up | awk -F': ' '$2!=\"lo\" {print $2; exit}'", timeout=10)
                iface = iface_res2.stdout.strip()
            if not iface:
                log("⚠️ Не удалось определить интерфейс на удалённом сервере.\n")
                return
        except Exception as e:
            log(f"⚠️ Ошибка определения интерфейса: {e}\n")
            return

        # sudo -n: не спрашивает пароль. Если требуется пароль — будет ошибка, но не зависнет.
        cmd = f"sudo -n arp-scan --interface {iface} --localnet"
        try:
            res = run_remote_cmd(CURRENT_HOST, cmd, timeout=60)
            if res.returncode == 0:
                log(res.stdout + "\n")
            else:
                log("❌ Remote arp-scan не выполнен.\n")
                log(f"stderr:\n{res.stderr}\n")
                log("ℹ️ На удалённом сервере нужен sudo без пароля для arp-scan,\n"
                    "   либо запускай arp-scan вручную в интерактивной сессии.\n")
        except Exception as e:
            log(f"⚠️ Ошибка remote arp-scan: {e}\n")

    threading.Thread(target=do_arp_scan, daemon=True).start()


# =========================
#  SSH proxy + Chromium
# =========================

def open_chromium(ip, new_tab=False):
    global chromium_process

    if not ip:
        log("⚠️ Не указан IP для Chromium.\n")
        return

    url = f"http://{ip}"
    if new_tab and chromium_process and chromium_process.poll() is None:
        log(f"🚀 Открываю новую вкладку {url} через прокси...\n")
        subprocess.run(["chromium", "--proxy-server=socks5://localhost:3000", "--new-tab", url])
    else:
        log(f"🚀 Открываю {url} через прокси...\n")
        chromium_process = subprocess.Popen(["chromium", "--proxy-server=socks5://localhost:3000", url])

def add_device():
    selected_ip = get_selected_ip()
    if not selected_ip:
        messagebox.showerror("Ошибка", "Укажи IP (в поле или выбери из списка)!", parent=root)
        return
    open_chromium(selected_ip, new_tab=True)

def start_ssh_connection(host, ip):
    global ssh_process

    port = 3000
    ssh_command = ["ssh", "-T", "-N", "-o", "StrictHostKeyChecking=no", "-D", f"127.0.0.1:{port}", host]

    def get_remote_ip():
        remote_ip_command = [
            "ssh", "-o", "StrictHostKeyChecking=no", host,
            "ip -4 addr show | awk '/inet / && $2 !~ /^127\\./ {print $2}' | cut -d'/' -f1 | head -n1"
        ]
        try:
            result = subprocess.run(
                remote_ip_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=12
            )
            if result.returncode == 0:
                rip = result.stdout.strip()
                return rip if rip else None
            log(f"⚠️ Не удалось получить IP: {result.stderr}\n")
        except Exception as e:
            log(f"⚠️ Ошибка получения IP: {str(e)}\n")
        return None

    def read_ssh_stderr(proc):
        try:
            while proc and proc.poll() is None:
                line = proc.stderr.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                log(f"[ssh] {line}")
        except Exception:
            pass

    def run_ssh():
        global ssh_process
        try:
            ensure_proxy_port_free(port)

            remote_ip = get_remote_ip()
            if remote_ip:
                log(f"🌐 Локальный IP удалённого сервера: {remote_ip}\n")
                current_dir = os.path.dirname(os.path.abspath(__file__))
                module_path = os.path.join(current_dir, "module.py")
                if os.path.exists(module_path):
                    try:
                        subprocess.run([sys.executable, module_path, remote_ip], check=True)
                    except subprocess.CalledProcessError as e:
                        log(f"⚠️ module.py завершился с ошибкой: {e}\n")
                else:
                    log("ℹ️ module.py не найден — пропускаю запуск.\n")
            else:
                log("⚠️ Не удалось получить локальный IP с удалённого сервера.\n")

            log(f"⏳ Подключение к {host} (SOCKS5 localhost:{port})...\n")
            ssh_process = subprocess.Popen(
                ssh_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            threading.Thread(target=read_ssh_stderr, args=(ssh_process,), daemon=True).start()

            time.sleep(2)
            if ssh_process.poll() is None:
                log("✅ SSH-прокси подключение установлено!\n")
                threading.Thread(target=check_proxy_ip, daemon=True).start()
                open_chromium(ip)
            else:
                err = ssh_process.stderr.read() if ssh_process.stderr else ""
                log(f"❌ SSH завершился сразу. Ошибка:\n{err}\n")

        except Exception as e:
            log(f"Ошибка: {str(e)}\n")

    threading.Thread(target=run_ssh, daemon=True).start()


# =========================
#  Actions
# =========================

def on_connect():
    global CURRENT_HOST

    selected_host = host_combobox.get().strip()
    selected_ip = get_selected_ip()

    if not selected_host:
        messagebox.showerror("Ошибка", "Выберите сервер!", parent=root)
        return

    if not selected_ip:
        messagebox.showerror("Ошибка", "Выберите/укажите IP!", parent=root)
        return

    # ✅ Предупреждение: при подключении закроем текущий Chromium (и вкладки) и запустим заново
    ok = messagebox.askokcancel(
        "Внимание",
        "При подключении текущие окна/вкладки Chromium, открытые этой программой, будут закрыты и Chromium будет запущен заново через прокси.\n\nПродолжить?",
        parent=root
    )
    if not ok:
        return

    CURRENT_HOST = selected_host
    close_existing_connections()
    start_ssh_connection(selected_host, selected_ip)

def on_ip_enter(event):
    on_connect()


def on_ip_combobox_selected(event=None):
    ip_entry.delete(0, tk.END)


def on_ip_combobox_enter(event):
    on_connect()

def disconnect():
    global CURRENT_HOST
    CURRENT_HOST = None
    close_existing_connections()


# =========================
#  GUI
# =========================

root = tk.Tk()
root.title("SSHProxy")
root.geometry("820x620")
root.configure(bg="#EEF3F8")

ip_addresses = load_ip_addresses()
ALL_SSH_HOSTS = get_ssh_hosts()

# ttk cosmetics
style = ttk.Style()
try:
    style.theme_use("clam")
except Exception:
    pass

BG_APP = "#EEF3F8"
BG_PANEL = "#FFFFFF"
BG_SUBTLE = "#F6F9FC"
TEXT_MAIN = "#16324F"
TEXT_MUTED = "#5B6B7A"
BORDER = "#D7E2EC"
ACCENT = "#1F6FEB"

style.configure("TCombobox", fieldbackground="#FFFFFF", background="#FFFFFF")
style.configure("TLabelframe", background=BG_APP, borderwidth=1, relief="solid")
style.configure("TLabelframe.Label", background=BG_APP, foreground=TEXT_MAIN, font=("Segoe UI", 10, "bold"))

# ====== Header ======
header_frame = tk.Frame(root, bg=BG_APP)
header_frame.pack(fill="x", padx=12, pady=(8, 4))

header_left = tk.Frame(header_frame, bg=BG_APP)
header_left.pack(side="left")

header_right = tk.Frame(header_frame, bg=BG_APP)
header_right.pack(side="right")

header_label = tk.Label(
    header_left,
    text="SSHProxy",
    font=("Segoe UI", 18, "bold"),
    bg=BG_APP,
    fg=TEXT_MAIN
)
header_label.pack(side="left")

# ====== Tools row ======
tools_frame = tk.Frame(root, bg=BG_APP)
tools_frame.pack(fill="x", padx=12, pady=(0, 6))

show_ssh_button = tk.Button(
    tools_frame,
    text="Показать SSH (3000)",
    command=show_active_ssh,
    bg=BG_PANEL,
    fg=TEXT_MAIN,
    activebackground=BG_SUBTLE,
    activeforeground=TEXT_MAIN,
    relief="solid",
    bd=1,
    padx=12,
    pady=6
)
show_ssh_button.pack(side="left", padx=6)

kill_3000_button = tk.Button(
    tools_frame,
    text="Освободить порт 3000",
    command=kill_proxy_3000,
    bg=BG_PANEL,
    fg=TEXT_MAIN,
    activebackground=BG_SUBTLE,
    activeforeground=TEXT_MAIN,
    relief="solid",
    bd=1,
    padx=12,
    pady=6
)
kill_3000_button.pack(side="left", padx=6)

# ====== Info ======
top_info = tk.Frame(root, bg=BG_APP)
top_info.pack(fill="x", padx=12, pady=(0, 6))

current_ip_label = tk.Label(
    top_info,
    text="Текущий IP: ---",
    fg=ACCENT,
    bg=BG_APP,
    font=("Segoe UI", 10, "bold")
)
current_ip_label.pack(anchor="w")

proxy_ip_label = tk.Label(
    top_info,
    text="IP через прокси: ---",
    fg="#137A2A",
    bg=BG_APP,
    font=("Segoe UI", 10, "bold")
)
proxy_ip_label.pack(anchor="w")

update_ip_labels()

# ====== Server block ======
server_block = tk.LabelFrame(
    root,
    text="Сервер",
    padx=12,
    pady=10,
    bg=BG_PANEL,
    fg=TEXT_MAIN,
    font=("Segoe UI", 10, "bold"),
    bd=1,
    relief="solid"
)
server_block.pack(fill="x", padx=12, pady=(0, 6))

host_label = tk.Label(
    server_block,
    text="Alias из ~/.ssh/config — начни вводить для поиска:",
    bg=BG_PANEL,
    fg=TEXT_MUTED,
    font=("Segoe UI", 10)
)
host_label.pack(anchor="w")

host_combobox = ttk.Combobox(server_block, values=ALL_SSH_HOSTS, width=60)
host_combobox.pack(fill="x", pady=(4, 0))
host_combobox.bind("<<ComboboxSelected>>", update_ip_list_by_selected_host)
host_combobox.bind("<KeyRelease>", on_host_keyrelease)
host_combobox.bind("<Return>", on_host_enter)

hosts_listbox = tk.Listbox(
    server_block,
    height=6,
    bg=BG_SUBTLE,
    fg=TEXT_MAIN,
    relief="solid",
    bd=1,
    highlightthickness=0,
    selectbackground=ACCENT,
    selectforeground="white"
)
hosts_listbox.bind("<<ListboxSelect>>", on_host_suggestion_click)
hosts_listbox.bind("<Double-Button-1>", on_host_suggestion_click)

selected_object_label = tk.Label(
    server_block,
    text="Объект: —",
    fg=TEXT_MUTED,
    bg=BG_PANEL,
    font=("Segoe UI", 10, "bold")
)
selected_object_label.pack(anchor="w", pady=(6, 0))

# ====== IP block ======
ip_block = tk.LabelFrame(
    root,
    text="IP / Устройства",
    padx=12,
    pady=10,
    bg=BG_PANEL,
    fg=TEXT_MAIN,
    font=("Segoe UI", 10, "bold"),
    bd=1,
    relief="solid"
)
ip_block.pack(fill="x", padx=12, pady=(0, 6))

ip_label = tk.Label(
    ip_block,
    text="Выбери IP из списка объекта или впиши вручную (Enter = подключиться):",
    bg=BG_PANEL,
    fg=TEXT_MUTED,
    font=("Segoe UI", 10)
)
ip_label.pack(anchor="w")

ip_combobox = ttk.Combobox(ip_block, values=[], state="disabled", width=60)
ip_combobox.pack(fill="x", pady=(4, 8))
ip_combobox.bind("<<ComboboxSelected>>", on_ip_combobox_selected)
ip_combobox.bind("<Return>", on_ip_combobox_enter)

ip_row = tk.Frame(ip_block, bg=BG_PANEL)
ip_row.pack(fill="x")

ip_entry = tk.Entry(
    ip_row,
    relief="solid",
    bd=1,
    highlightthickness=0,
    font=("Segoe UI", 10)
)
ip_entry.pack(side="left", fill="x", expand=True)
ip_entry.bind("<Return>", on_ip_enter)

save_ip_button = tk.Button(
    ip_row,
    text="Сохранить IP",
    command=save_current_ip,
    bg=BG_PANEL,
    fg=TEXT_MAIN,
    activebackground=BG_SUBTLE,
    activeforeground=TEXT_MAIN,
    relief="solid",
    bd=1,
    padx=12,
    pady=6
)
save_ip_button.pack(side="left", padx=8)

# ====== Actions ======
actions_block = tk.LabelFrame(
    root,
    text="Действия",
    padx=12,
    pady=10,
    bg=BG_PANEL,
    fg=TEXT_MAIN,
    font=("Segoe UI", 10, "bold"),
    bd=1,
    relief="solid"
)
actions_block.pack(fill="x", padx=12, pady=(0, 6))

connect_button = tk.Button(
    actions_block,
    text="Подключиться",
    command=on_connect,
    bg="#16A34A", fg="white",
    activebackground="#15803D", activeforeground="white",
    font=("Segoe UI", 11, "bold"),
    padx=14, pady=8
)
connect_button.pack(side="left", padx=6)

disconnect_button = tk.Button(
    actions_block,
    text="Отключиться",
    command=disconnect,
    bg="#DC2626", fg="white",
    activebackground="#B91C1C", activeforeground="white",
    font=("Segoe UI", 11, "bold"),
    padx=14, pady=8
)
disconnect_button.pack(side="left", padx=6)

open_tab_button = tk.Button(
    actions_block,
    text="Открыть устройство (вкладка)",
    command=add_device,
    bg="#2563EB", fg="white",
    activebackground="#1D4ED8", activeforeground="white",
    font=("Segoe UI", 11, "bold"),
    padx=14, pady=8
)
open_tab_button.pack(side="left", padx=6)

# ====== Log ======
terminal_block = tk.LabelFrame(root, text="Лог", padx=10, pady=8)
terminal_block.pack(fill="both", expand=True, padx=12, pady=(0, 12))

terminal = tk.Text(
    terminal_block,
    height=28,
    bg="#F8FBFE",
    fg=TEXT_MAIN,
    insertbackground=TEXT_MAIN,
    relief="solid",
    bd=1,
    highlightthickness=0,
    font=("Consolas", 10)
)
terminal.pack(fill="both", expand=True)

log("ℹ️ Подсказка:\n")
log(" • Ввод в поле 'Сервер' фильтрует список по первым буквам / вхождению.\n")
log(" • Объект подставляется автоматически по имени сервера.\n")
log(" • Enter в поле IP = Подключиться.\n")
log(" • Кнопка 'Сохранить IP' добавляет вручную введённый адрес в config.xlsx.\n")
log(" • Enter в списке IP тоже запускает подключение.\n\n")

root.mainloop()
