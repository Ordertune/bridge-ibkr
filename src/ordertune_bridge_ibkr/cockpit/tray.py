"""Das Tray-Symbol: woran man sieht, dass die Bridge noch laeuft.

## Warum es das gibt

Seit T1-213 ist die EXE fensterlos. Das Cockpit ist ein Browserfenster, und wer
es schliesst, beendet damit nicht die Bridge — sie handelt weiter. Bis hierher
war das nirgends zu sehen: kein Eintrag in der Taskleiste, kein Symbol, nur
eine Zeile im Task-Manager.

Ein Test-User schickte daraufhin einen Screenshot von `tws_api_refused`. Die
naheliegende Lesart: er hielt die Bridge mit dem Fenster fuer beendet, klickte
erneut, und der zweite Start kollidierte auf der Client-ID. T1-222 faengt den
zweiten Klick inzwischen ab — aber die Frage, ob die Bridge laeuft, sollte man
gar nicht erst durch einen zweiten Klick beantworten muessen.

Das Symbol zeigt deshalb drei Dinge: DASS sie laeuft (es ist da), WIE es ihr
geht (der Punkt), und WIE man sie erreicht oder beendet (das Menue). Beim
ersten Schliessen des Fensters sagt eine Windows-Benachrichtigung einmal, dass
die Bridge weiterlaeuft und wo das Symbol sitzt.

## Warum `ctypes` und kein Werkzeugkasten

Dieselbe Begruendung wie in `windows_ui.py` und `window.py`: `pystray` braeuchte
Pillow zur Laufzeit, und die EXE ist unsigniert — weniger Beiwerk ist weniger
Anlass fuer Defender. `Shell_NotifyIconW` steht in jeder Windows-Installation.

## Die Richtungsregel gilt auch hier

Das Symbol LIEST den Zustandsblock und setzt hoechstens die Halte-Fahne —
dieselbe, die der Knopf im Cockpit setzt (T1-223). Es fasst weder die
IBKR-Verbindung noch den Server an.

## Warum hier nichts wirft

Das Symbol ist Beiwerk. Jeder Fehler kostet das Symbol, nie den Handel.
"""
from __future__ import annotations

import base64
import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)

# ── Reine Logik (ohne Windows pruefbar) ──────────────────────────────────────

RUNNING = "running"
ATTENTION = "attention"
STOPPING = "stopping"

# Windows schneidet den Tooltip bei 127 Zeichen ab.
TIP_MAX = 127

# Wie lange kein Fenster mehr verbunden sein muss, bevor der Hinweis kommt.
# Ein Neuladen der Seite trennt den Ereignisstrom fuer einen Augenblick; das
# ist kein Schliessen.
CLOSED_GRACE_S = 5.0

BALLOON_TITLE = "Ordertune Bridge is still running"
BALLOON_TEXT = (
    "Closing the window does not stop the Bridge. Use this icon to open the "
    "window again or to stop the Bridge."
)

MENU_OPEN = "Open window"
MENU_STOP = "Stop the Bridge"


def status_of(state: Any) -> str:
    """Welcher Punkt? Aus dem Zustandsblock, ohne eigene Wahrheit."""
    if getattr(state, "stopping", False):
        return STOPPING
    if getattr(state, "failure_code", None):
        return ATTENTION
    if not getattr(state, "tws_connected", False) or not getattr(state, "ordertune_ok", False):
        return ATTENTION
    return RUNNING


def tooltip_of(state: Any) -> str:
    """Der Text beim Ueberfahren. Kurz, weil Windows bei 127 Zeichen schneidet."""
    status = status_of(state)
    if status == STOPPING:
        zeile = "stopping"
    elif getattr(state, "failure_headline", None):
        zeile = str(state.failure_headline)
    elif not getattr(state, "tws_connected", False):
        zeile = "no connection to TWS"
    elif not getattr(state, "ordertune_ok", False):
        zeile = "Ordertune not reachable"
    else:
        zeile = "running"
    text = f"Ordertune Bridge: {zeile}"
    konto = getattr(state, "account_masked", None)
    if konto and status != STOPPING:
        text += f"\nAccount {konto}"
    if len(text) > TIP_MAX:
        text = text[: TIP_MAX - 3] + "..."
    return text


@dataclass
class ClosedWindowNotice:
    """Wann der Hinweis „laeuft weiter" kommt: einmal je Sitzung.

    Bedingung: es war schon einmal ein Fenster verbunden, jetzt seit
    `CLOSED_GRACE_S` keines mehr, und die Bridge wird nicht gerade beendet.
    Ohne die erste Bedingung kaeme der Hinweis auch dann, wenn das Fenster nie
    aufging — etwa ohne Browser —, und das waere ein Hinweis auf etwas, das
    der Nutzer nicht getan hat.
    """

    grace_s: float = CLOSED_GRACE_S
    _seen_window: bool = False
    _empty_since: float | None = None
    _shown: bool = False

    def due(self, open_windows: int, stopping: bool, now: float) -> bool:
        if self._shown:
            return False
        if open_windows > 0:
            self._seen_window = True
            self._empty_since = None
            return False
        if not self._seen_window or stopping:
            self._empty_since = None
            return False
        if self._empty_since is None:
            self._empty_since = now
            return False
        if now - self._empty_since >= self.grace_s:
            self._shown = True
            return True
        return False


def ico_frames(data: bytes) -> list[tuple[int, bytes]]:
    """(Groesse, Rahmen-Nutzlast) je Eintrag eines ICO."""
    count = int.from_bytes(data[4:6], "little")
    frames = []
    for i in range(count):
        entry = 6 + i * 16
        size = data[entry] or 256
        length = int.from_bytes(data[entry + 8:entry + 12], "little")
        offset = int.from_bytes(data[entry + 12:entry + 16], "little")
        frames.append((size, data[offset:offset + length]))
    return frames


def pick_frame(data: bytes, wanted: int) -> tuple[int, bytes]:
    """Der kleinste Rahmen, der mindestens `wanted` gross ist, sonst der groesste.

    Herunterskalieren sieht besser aus als hochskalieren — und Windows
    skaliert selbst, wenn die Groesse nicht passt.
    """
    frames = sorted(ico_frames(data))
    for size, payload in frames:
        if size >= wanted:
            return size, payload
    return frames[-1]


def icon_bytes(status: str) -> bytes:
    from . import tray_icons

    return base64.b64decode("".join(getattr(tray_icons, status.upper())))


# ── Windows ──────────────────────────────────────────────────────────────────

_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_NULL = 0x0000
_WM_TIMER = 0x0113
_WM_COMMAND = 0x0111
_WM_LBUTTONUP = 0x0202
_WM_RBUTTONUP = 0x0205
_WM_CONTEXTMENU = 0x007B
_WM_APP = 0x8000
_CALLBACK_MSG = _WM_APP + 1

_NIM_ADD = 0
_NIM_MODIFY = 1
_NIM_DELETE = 2
_NIF_MESSAGE = 0x01
_NIF_ICON = 0x02
_NIF_TIP = 0x04
_NIF_INFO = 0x10
_NIIF_INFO = 0x01

_MF_STRING = 0x0000
_MF_SEPARATOR = 0x0800
_MF_GRAYED = 0x0001
_TPM_RIGHTBUTTON = 0x0002
_TPM_RETURNCMD = 0x0100
_TPM_NONOTIFY = 0x0080
_SM_CXSMICON = 49

_CMD_OPEN = 1
_CMD_STOP = 2
_TIMER_ID = 1
_TIMER_MS = 1000

_CLASS_NAME = "OrdertuneBridgeTray"
_ERROR_CLASS_ALREADY_EXISTS = 1410


def _win32() -> Any:
    """Die Windows-Aufrufe mit ihren Signaturen. Erst hier importiert."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LRESULT = wintypes.LPARAM
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_ubyte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    # Eine Liste, kein dict: ctypes-Funktionszeiger sind nicht hashbar.
    sig = [
        (user32.DefWindowProcW, LRESULT, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
        (user32.RegisterClassExW, wintypes.ATOM, [ctypes.POINTER(WNDCLASSEXW)]),
        (user32.CreateWindowExW, wintypes.HWND, [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]),
        (user32.DestroyWindow, wintypes.BOOL, [wintypes.HWND]),
        (user32.GetMessageW, wintypes.BOOL, [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]),
        (user32.TranslateMessage, wintypes.BOOL, [ctypes.POINTER(wintypes.MSG)]),
        (user32.DispatchMessageW, LRESULT, [ctypes.POINTER(wintypes.MSG)]),
        (user32.PostMessageW, wintypes.BOOL, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
        (user32.PostQuitMessage, None, [ctypes.c_int]),
        (user32.RegisterWindowMessageW, wintypes.UINT, [wintypes.LPCWSTR]),
        (user32.SetTimer, ctypes.c_size_t, [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]),
        (user32.KillTimer, wintypes.BOOL, [wintypes.HWND, ctypes.c_size_t]),
        (user32.CreatePopupMenu, wintypes.HMENU, []),
        (user32.AppendMenuW, wintypes.BOOL, [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]),
        (user32.TrackPopupMenu, wintypes.BOOL, [
            wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.LPVOID,
        ]),
        (user32.DestroyMenu, wintypes.BOOL, [wintypes.HMENU]),
        (user32.GetCursorPos, wintypes.BOOL, [ctypes.POINTER(POINT)]),
        (user32.SetForegroundWindow, wintypes.BOOL, [wintypes.HWND]),
        (user32.GetSystemMetrics, ctypes.c_int, [ctypes.c_int]),
        (user32.CreateIconFromResourceEx, wintypes.HICON, [
            ctypes.c_char_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]),
        (user32.DestroyIcon, wintypes.BOOL, [wintypes.HICON]),
        (shell32.Shell_NotifyIconW, wintypes.BOOL, [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]),
        (kernel32.GetModuleHandleW, wintypes.HMODULE, [wintypes.LPCWSTR]),
    ]
    for fn, restype, argtypes in sig:
        fn.restype = restype
        fn.argtypes = argtypes

    class _Api:
        pass

    api = _Api()
    api.ctypes = ctypes
    api.wintypes = wintypes
    api.user32 = user32
    api.shell32 = shell32
    api.kernel32 = kernel32
    api.WNDPROC = WNDPROC
    api.WNDCLASSEXW = WNDCLASSEXW
    api.NOTIFYICONDATAW = NOTIFYICONDATAW
    api.POINT = POINT
    return api


def make_hicon(api: Any, status: str) -> Any:
    """Ein Symbol aus den eingebetteten Bytes, passend zur Skalierung."""
    wanted = api.user32.GetSystemMetrics(_SM_CXSMICON) or 16
    size, payload = pick_frame(icon_bytes(status), wanted)
    hicon = api.user32.CreateIconFromResourceEx(
        payload, len(payload), True, 0x00030000, size, size, 0
    )
    if not hicon:
        raise OSError(f"CreateIconFromResourceEx failed ({api.ctypes.get_last_error()})")
    return hicon


class TrayIcon:
    """Das Symbol mit eigenem Thread und eigener Nachrichtenschleife.

    Alle Windows-Aufrufe laufen auf diesem Thread. Von aussen kommen nur
    `stop()` (eine gepostete Nachricht) und die Lesezugriffe des Taktgebers.
    """

    def __init__(
        self,
        *,
        read_state: Callable[[], Any],
        open_window: Callable[[], None],
        on_stop: Callable[[], None],
        open_windows: Callable[[], int] = lambda: 0,
    ) -> None:
        self._read_state = read_state
        self._open_window = open_window
        self._on_stop = on_stop
        self._open_windows = open_windows
        self._notice = ClosedWindowNotice()
        self._hwnd: Any = None
        self._api: Any = None
        self._icons: dict[str, Any] = {}
        self._shown: tuple[str, str] | None = None
        self._added = False
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._taskbar_created = 0
        self._wndproc: Any = None

    # ── von aussen ───────────────────────────────────────────────────────

    def start(self, timeout: float = 5.0) -> bool:
        """Startet den Thread. Gibt zurueck, ob das Symbol steht."""
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self._added

    def stop(self, timeout: float = 5.0) -> None:
        if self._hwnd and self._api is not None:
            self._api.user32.PostMessageW(self._hwnd, _WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def visible(self) -> bool:
        return self._added

    # ── der Thread ───────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            self._api = api = _win32()
            hinstance = api.kernel32.GetModuleHandleW(None)
            self._wndproc = api.WNDPROC(self._proc)
            wc = api.WNDCLASSEXW()
            wc.cbSize = api.ctypes.sizeof(api.WNDCLASSEXW)
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinstance
            wc.lpszClassName = _CLASS_NAME
            if not api.user32.RegisterClassExW(api.ctypes.byref(wc)):
                fehler = api.ctypes.get_last_error()
                if fehler != _ERROR_CLASS_ALREADY_EXISTS:
                    raise OSError(f"RegisterClassExW failed ({fehler})")
            # Ein unsichtbares Fenster, kein reines Nachrichtenfenster: nur ein
            # echtes Fenster bekommt `TaskbarCreated` (Explorer-Neustart) und
            # kann ein Kontextmenue besitzen.
            self._hwnd = api.user32.CreateWindowExW(
                0, _CLASS_NAME, "Ordertune Bridge", 0, 0, 0, 0, 0,
                None, None, hinstance, None,
            )
            if not self._hwnd:
                raise OSError(f"CreateWindowExW failed ({api.ctypes.get_last_error()})")
            self._taskbar_created = api.user32.RegisterWindowMessageW("TaskbarCreated")
            for status in (RUNNING, ATTENTION, STOPPING):
                self._icons[status] = make_hicon(api, status)
            self._refresh(force_add=True)
            api.user32.SetTimer(self._hwnd, _TIMER_ID, _TIMER_MS, None)
        except Exception as exc:  # noqa: BLE001 - Beiwerk
            log.warning("Tray icon could not start (the Bridge keeps running): %s", exc)
            self._ready.set()
            self._cleanup()
            return
        self._ready.set()

        msg = api.wintypes.MSG()
        try:
            while api.user32.GetMessageW(api.ctypes.byref(msg), None, 0, 0) > 0:
                api.user32.TranslateMessage(api.ctypes.byref(msg))
                api.user32.DispatchMessageW(api.ctypes.byref(msg))
        except Exception as exc:  # noqa: BLE001 - Beiwerk
            log.warning("Tray icon stopped unexpectedly: %s", exc)
        finally:
            self._cleanup()

    def _proc(self, hwnd: Any, msg: int, wparam: int, lparam: int) -> int:
        api = self._api
        try:
            if msg == _CALLBACK_MSG:
                ereignis = lparam & 0xFFFF
                if ereignis == _WM_LBUTTONUP:
                    self._safe(self._open_window)
                elif ereignis in (_WM_RBUTTONUP, _WM_CONTEXTMENU):
                    self._menu()
                return 0
            if msg == _WM_TIMER:
                self._refresh()
                return 0
            if msg == _WM_CLOSE:
                api.user32.KillTimer(hwnd, _TIMER_ID)
                self._delete()
                api.user32.DestroyWindow(hwnd)
                return 0
            if msg == _WM_DESTROY:
                api.user32.PostQuitMessage(0)
                return 0
            if self._taskbar_created and msg == self._taskbar_created:
                # Explorer wurde neu gestartet; alle Symbole sind weg.
                self._added = False
                self._refresh(force_add=True)
                return 0
        except Exception as exc:  # noqa: BLE001 - Beiwerk
            log.debug("Tray message %s failed: %s", msg, exc)
        return api.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _safe(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - Beiwerk
            log.warning("Tray action failed: %s", exc)

    def _menu(self) -> None:
        api = self._api
        state = self._read_state()
        menu = api.user32.CreatePopupMenu()
        try:
            api.user32.AppendMenuW(menu, _MF_STRING, _CMD_OPEN, MENU_OPEN)
            api.user32.AppendMenuW(menu, _MF_SEPARATOR, 0, None)
            stop_flags = _MF_STRING | (_MF_GRAYED if getattr(state, "stopping", False) else 0)
            api.user32.AppendMenuW(menu, stop_flags, _CMD_STOP, MENU_STOP)
            punkt = api.POINT()
            api.user32.GetCursorPos(api.ctypes.byref(punkt))
            # Ohne das schliesst das Menue nicht, wenn man daneben klickt.
            api.user32.SetForegroundWindow(self._hwnd)
            wahl = api.user32.TrackPopupMenu(
                menu, _TPM_RIGHTBUTTON | _TPM_RETURNCMD | _TPM_NONOTIFY,
                punkt.x, punkt.y, 0, self._hwnd, None,
            )
            api.user32.PostMessageW(self._hwnd, _WM_NULL, 0, 0)
        finally:
            api.user32.DestroyMenu(menu)
        if wahl == _CMD_OPEN:
            self._safe(self._open_window)
        elif wahl == _CMD_STOP:
            self._safe(self._on_stop)
            self._refresh()

    def _data(self, flags: int) -> Any:
        api = self._api
        nid = api.NOTIFYICONDATAW()
        nid.cbSize = api.ctypes.sizeof(api.NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = _CALLBACK_MSG
        return nid

    def _refresh(self, force_add: bool = False) -> None:
        api = self._api
        state = self._read_state()
        status, tip = status_of(state), tooltip_of(state)
        if force_add or not self._added or self._shown != (status, tip):
            nid = self._data(_NIF_MESSAGE | _NIF_ICON | _NIF_TIP)
            nid.hIcon = self._icons[status]
            nid.szTip = tip
            if not self._added:
                self._added = bool(api.shell32.Shell_NotifyIconW(_NIM_ADD, api.ctypes.byref(nid)))
                if not self._added:
                    log.debug("Shell_NotifyIconW(NIM_ADD) failed (%s)", api.ctypes.get_last_error())
            else:
                api.shell32.Shell_NotifyIconW(_NIM_MODIFY, api.ctypes.byref(nid))
            self._shown = (status, tip)

        if self._added and self._notice.due(
            self._open_windows(), bool(getattr(state, "stopping", False)), time.monotonic()
        ):
            nid = self._data(_NIF_INFO)
            nid.szInfoTitle = BALLOON_TITLE
            nid.szInfo = BALLOON_TEXT
            nid.dwInfoFlags = _NIIF_INFO
            api.shell32.Shell_NotifyIconW(_NIM_MODIFY, api.ctypes.byref(nid))
            log.info("Cockpit window closed — the Bridge keeps running in the tray.")

    def _delete(self) -> None:
        if self._added:
            nid = self._data(0)
            self._api.shell32.Shell_NotifyIconW(_NIM_DELETE, self._api.ctypes.byref(nid))
            self._added = False

    def _cleanup(self) -> None:
        try:
            if self._api is not None:
                self._delete()
                for hicon in self._icons.values():
                    self._api.user32.DestroyIcon(hicon)
                self._icons.clear()
        except Exception as exc:  # noqa: BLE001 - defensiv
            log.debug("Tray cleanup failed: %s", exc)
        self._hwnd = None


def start_tray(
    *,
    read_state: Callable[[], Any],
    open_window: Callable[[], None],
    on_stop: Callable[[], None],
    open_windows: Callable[[], int] = lambda: 0,
) -> TrayIcon | None:
    """Das Symbol, wenn es eins geben kann. Ausserhalb von Windows: nichts."""
    if sys.platform != "win32":
        return None
    try:
        tray = TrayIcon(
            read_state=read_state,
            open_window=open_window,
            on_stop=on_stop,
            open_windows=open_windows,
        )
        if not tray.start():
            log.warning("Tray icon is not visible; the Bridge keeps running.")
        return tray
    except Exception as exc:  # noqa: BLE001 - Beiwerk
        log.warning("Tray icon could not start (the Bridge keeps running): %s", exc)
        return None
