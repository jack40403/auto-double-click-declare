"""Exercise real Win32 selection/replacement in a hidden, separate test process.

Creates only test-owned controls. Never uses a pharmacy HWND, real keyboard input,
clipboard, foreground activation, or the user's IME settings.
"""
import ctypes
import multiprocessing
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def edit_fixture(connection):
    from ctypes import wintypes
    import win32con
    import win32gui

    parent = None
    try:
        # No WS_VISIBLE on the parent: these controls never appear on the desktop.
        parent = win32gui.CreateWindowEx(
            0, "STATIC", "F10 test fixture", win32con.WS_OVERLAPPEDWINDOW,
            0, 0, 320, 180, 0, 0, 0, None)
        style = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.ES_AUTOHSCROLL
        month = win32gui.CreateWindowEx(0, "EDIT", "11510", style, 10, 10, 110, 25, parent, 1, 0, None)

        create_ansi = ctypes.windll.user32.CreateWindowExA
        create_ansi.argtypes = [
            wintypes.DWORD, ctypes.c_char_p, ctypes.c_char_p, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
        ]
        create_ansi.restype = wintypes.HWND
        serial = create_ansi(0, b"EDIT", b"9999", style, 10, 50, 110, 25, parent, 2, None, None)
        if not serial:
            raise OSError("Could not create ANSI test edit")
        # A system EDIT may be Unicode even when created with CreateWindowExA.
        # Install an ANSI window procedure and let CallWindowProcA perform the
        # documented conversion when forwarding to the system edit procedure.
        get_proc = ctypes.windll.user32.GetWindowLongPtrA
        get_proc.argtypes = [wintypes.HWND, ctypes.c_int]
        get_proc.restype = ctypes.c_ssize_t
        serial_original_proc = get_proc(serial, win32con.GWL_WNDPROC)
        call_ansi = ctypes.windll.user32.CallWindowProcA
        call_ansi.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        call_ansi.restype = ctypes.c_ssize_t
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        @callback_type
        def serial_ansi_proc(hwnd, message, wparam, lparam):
            return call_ansi(serial_original_proc, hwnd, message, wparam, lparam)
        set_proc = ctypes.windll.user32.SetWindowLongPtrA
        set_proc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_proc.restype = ctypes.c_ssize_t
        set_proc(serial, win32con.GWL_WNDPROC, ctypes.cast(serial_ansi_proc, ctypes.c_void_p).value)
        is_unicode = ctypes.windll.user32.IsWindowUnicode
        is_unicode.argtypes = [wintypes.HWND]
        is_unicode.restype = wintypes.BOOL
        win32gui.SendMessage(month, win32con.EM_SETLIMITTEXT, 5, 0)
        win32gui.SendMessage(serial, win32con.EM_SETLIMITTEXT, 4, 0)
        selections = []
        keyboard_messages = []
        refuse_selection = False
        original_proc = None

        def track(hwnd, message, wparam, lparam):
            if message in (
                win32con.WM_KEYDOWN, win32con.WM_CHAR,
                win32con.WM_IME_STARTCOMPOSITION, win32con.WM_IME_COMPOSITION,
            ):
                keyboard_messages.append(message)
            if message == win32con.EM_SETSEL and refuse_selection:
                return 0
            if message == win32con.WM_SETTEXT:
                selected = win32gui.SendMessage(hwnd, win32con.EM_GETSEL, 0, 0)
                selections.append((selected & 0xFFFF, (selected >> 16) & 0xFFFF))
            return win32gui.CallWindowProc(original_proc, hwnd, message, wparam, lparam)

        original_proc = win32gui.SetWindowLong(month, win32con.GWL_WNDPROC, track)
        connection.send({"month": month, "serial": serial})
        while True:
            win32gui.PumpWaitingMessages()
            if not connection.poll(0.005):
                continue
            request = connection.recv()
            if request["command"] == "stop":
                break
            if request["command"] == "reset":
                refuse_selection = False
                win32gui.SetWindowText(month, request.get("month", "11510"))
                win32gui.SetWindowText(serial, request.get("serial", "9999"))
                win32gui.SendMessage(month, win32con.EM_SETSEL, 0, 0)
                selections.clear()
                keyboard_messages.clear()
                connection.send(True)
            elif request["command"] == "refuse_selection":
                refuse_selection = True
                connection.send(True)
            elif request["command"] == "snapshot":
                connection.send({
                    "month": win32gui.GetWindowText(month),
                    "serial": win32gui.GetWindowText(serial),
                    "serial_is_unicode": bool(is_unicode(serial)),
                    "selections_at_write": selections,
                    "keyboard_messages": keyboard_messages,
                })
    except Exception as exc:
        connection.send({"error": repr(exc)})
    finally:
        if parent:
            win32gui.DestroyWindow(parent)
        connection.close()


class NativeEditSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from Automation_Engine import AutomationEngine
        cls.engine = AutomationEngine(None)
        context = multiprocessing.get_context("spawn")
        cls.connection, child = context.Pipe()
        cls.process = context.Process(target=edit_fixture, args=(child,))
        cls.process.start()
        child.close()
        if not cls.connection.poll(30):
            cls.process.terminate()
            cls.process.join(5)
            raise RuntimeError("Native edit fixture did not start")
        cls.handles = cls.connection.recv()
        if "error" in cls.handles:
            cls.process.join(5)
            raise RuntimeError(cls.handles["error"])

    @classmethod
    def tearDownClass(cls):
        if cls.process.is_alive():
            try:
                cls.connection.send({"command": "stop"})
            except (OSError, EOFError):
                pass
        cls.process.join(5)
        if cls.process.is_alive():
            cls.process.terminate()  # Test-owned subprocess only.
            cls.process.join(5)
        cls.connection.close()

    def request(self, command, **kwargs):
        self.connection.send({"command": command, **kwargs})
        self.assertTrue(self.connection.poll(5), "Fixture response timed out")
        response = self.connection.recv()
        if isinstance(response, dict):
            self.assertNotIn("error", response)
        return response

    def setUp(self):
        self.engine.stop_event.clear()
        self.request("reset")

    def test_real_selection_and_full_replace_without_keyboard_or_ime(self):
        self.assertTrue(self.engine._replace_edit_text(self.handles["month"], "11509"))
        result = self.request("snapshot")
        self.assertEqual(result["month"], "11509")
        self.assertEqual(result["serial"], "9999")
        self.assertEqual(result["selections_at_write"], [(0, 5)])
        self.assertEqual(result["keyboard_messages"], [])

    def test_damaged_four_character_month_is_fully_replaced(self):
        self.request("reset", month="1151")
        self.engine._replace_edit_text(self.handles["month"], "11509")
        result = self.request("snapshot")
        self.assertEqual(result["month"], "11509")
        self.assertEqual(result["selections_at_write"], [(0, 4)])

    def test_non_ascii_old_text_leaves_no_residue(self):
        self.request("reset", month="１１五月")
        self.engine._replace_edit_text(self.handles["month"], "11509")
        result = self.request("snapshot")
        self.assertEqual(result["month"], "11509")
        self.assertEqual(result["selections_at_write"], [(0, 4)])
        self.assertEqual(result["keyboard_messages"], [])

    def test_ansi_legacy_control_preserves_serial_leading_zeros(self):
        self.engine._replace_edit_text(self.handles["serial"], "0010")
        result = self.request("snapshot")
        self.assertFalse(result["serial_is_unicode"])
        self.assertEqual(result["serial"], "0010")
        self.assertEqual(result["month"], "11510")

    def test_refused_select_all_stops_without_changing_text(self):
        self.request("refuse_selection")
        with self.assertRaisesRegex(RuntimeError, "全部選取"):
            self.engine._replace_edit_text(self.handles["month"], "11509")
        result = self.request("snapshot")
        self.assertEqual(result["month"], "11510")
        self.assertEqual(result["selections_at_write"], [])

    def test_cancelled_operation_does_not_change_native_control(self):
        self.engine.stop_event.set()
        with self.assertRaises(InterruptedError):
            self.engine._replace_edit_text(self.handles["month"], "11509")
        self.assertEqual(self.request("snapshot")["month"], "11510")

    def test_full_width_requested_digits_are_rejected(self):
        with self.assertRaises(ValueError):
            self.engine._replace_edit_text(self.handles["month"], "１１５０９")
        self.assertEqual(self.request("snapshot")["month"], "11510")


if __name__ == "__main__":
    unittest.main(verbosity=2)
