"""F10 regression smoke: real installed EasyOCR + cropped user-supplied dialog.

Only the Windows input/control boundary is simulated; no pharmacy data is changed.
Run: venv/Scripts/python.exe tests/test_f10_smoke.py
"""
import sys
import unittest
import ctypes
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import easyocr
import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import Automation_Engine as module


class F10Smoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.reference = Image.open(ROOT / "tests" / "fixtures" / "f10-popup.png").convert("RGB")
        cls.reader = easyocr.Reader(
            ["ch_tra", "en"], model_storage_directory=str(ROOT / "models"),
            gpu=False, download_enabled=False, verbose=False,
        )

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.popup = SimpleNamespace(
            title="銷售修改", _hWnd=100, left=845, top=438, width=229, height=201,
            isMinimized=False, activate=Mock(), restore=Mock(),
        )
        # Native labels are absent, as in the observed legacy dialog.
        self.rects = {11: (943, 520, 1054, 545), 12: (943, 560, 1054, 585)}
        self.values = {11: "11510", 12: ""}
        self.focus = None
        self.rejected = set()
        self.selection = {}
        self.reject_selection = set()
        self.actions = []
        self.messages = []
        self.engine = module.AutomationEngine(SimpleNamespace(reader=self.reader))
        self.engine.fixed_pos = (300, 200)

        def replace(obj, name, **kwargs):
            return self.stack.enter_context(patch.object(obj, name, **kwargs))

        replace(module.win32gui, "EnumChildWindows",
                side_effect=lambda _h, callback, extra: [callback(h, extra) for h in self.rects])
        replace(module.win32gui, "IsWindowVisible", return_value=True)
        replace(module.win32gui, "IsWindow", return_value=True)
        replace(module.win32gui, "IsChild", side_effect=lambda parent, child: parent == 100 and child in self.rects)
        replace(module.win32gui, "IsWindowEnabled", return_value=True)
        replace(module.win32gui, "GetWindowText", side_effect=lambda h: self.popup.title if h == 100 else self.values[h])
        replace(module.win32gui, "GetWindowLong", return_value=0)
        replace(module.win32gui, "GetWindowRect", side_effect=lambda h: self.rects[h])
        replace(module.win32gui, "GetClassName", return_value="ThunderRT6TextBox")
        replace(self.engine, "_read_edit_text", side_effect=lambda h: self.values[h])
        replace(self.engine, "_send_control_message", side_effect=self.control_message)
        replace(module.pyautogui, "size", return_value=(1920, 1080))

        def screenshot(*, region):
            self.assertEqual(region, (845, 438, 229, 201))
            return self.reference.copy()

        replace(module.pyautogui, "screenshot", side_effect=screenshot)
        replace(module.time, "sleep", return_value=None)
        replace(self.engine, "_wait_for_input_popup", return_value=self.popup)
        replace(module.pyautogui, "click", side_effect=self.click)
        replace(module.pyautogui, "write", side_effect=AssertionError("IME-dependent typing is forbidden"))
        replace(module.pyautogui, "press", side_effect=self.press)
        replace(module.pyautogui, "hotkey", side_effect=lambda *keys: self.actions.append(("hotkey", keys)))
        replace(module.pyautogui, "moveTo", return_value=None)
        replace(module.pyautogui, "doubleClick", return_value=None)

    def click(self, x=None, y=None):
        self.actions.append(("click", (x, y)))
        if x is not None and y is not None:
            self.focus = next((h for h, (l, t, r, b) in self.rects.items()
                               if l <= x <= r and t <= y <= b), None)

    def control_message(self, hwnd, message, wparam=0, lparam=0):
        if message == module.win32con.EM_SETSEL:
            if hwnd not in self.reject_selection:
                self.selection[hwnd] = (0, len(self.values[hwnd]))
            self.actions.append(("select_all", hwnd))
            return 0  # EM_SETSEL has no result value; delivery success is separate.
        if message == module.win32con.EM_GETSEL:
            start, end = self.selection.get(hwnd, (0, 0))
            if wparam:
                ctypes.c_uint32.from_address(wparam).value = start
            if lparam:
                ctypes.c_uint32.from_address(lparam).value = end
            return start | (end << 16)
        if message == module.win32con.WM_SETTEXT:
            value = ctypes.wstring_at(lparam)
            self.assertEqual(self.selection[hwnd], (0, len(self.values[hwnd])))
            self.actions.append(("replace", hwnd, value))
            if hwnd in self.rejected:
                return 0
            self.values[hwnd] = value
            return 1
        raise AssertionError(f"Unexpected message: {message}")

    def press(self, key):
        self.actions.append(("press", key))
        self.assertNotEqual(key, "backspace", "Native replacement must not type Backspace")

    def workflow(self, month="11510"):
        return self.engine._run_single_workflow("01151001234", self.messages.append, month)

    def test_real_ocr_recognizes_reference_when_native_text_unavailable(self):
        self.values = {11: "", 12: ""}
        with patch.object(self.reader, "readtext", wraps=self.reader.readtext) as actual_ocr:
            fields = self.engine._read_popup_fields(self.popup, self.messages.append)
        self.assertIsNotNone(fields, self.messages)
        self.assertEqual(fields["month"]["value"], "11510")
        self.assertEqual(fields["serial"]["value"], "")
        self.assertEqual(fields["month"]["position"], (998, 532))
        self.assertEqual(fields["serial"]["position"], (998, 572))
        self.assertIsInstance(actual_ocr.call_args.args[0], np.ndarray)

    def test_native_values_work_without_chinese_label_ocr(self):
        self.values[12] = "1234"
        with patch.object(self.reader, "readtext", side_effect=AssertionError("OCR not needed")):
            fields = self.engine._read_popup_fields(self.popup, self.messages.append)
        self.assertEqual(fields["month"]["value"], "11510")
        self.assertEqual(fields["serial"]["value"], "1234")

    def test_native_empty_serial_does_not_require_ocr(self):
        with patch.object(self.reader, "readtext", side_effect=AssertionError("Blank serial is valid")):
            fields = self.engine._read_popup_fields(self.popup, self.messages.append)
        self.assertEqual(fields["serial"]["value"], "")

    def test_matching_month_only_writes_serial(self):
        self.assertTrue(self.workflow(), self.messages)
        self.assertEqual([a for a in self.actions if a[0] == "replace"], [("replace", 12, "1234")])

    def test_changed_month_then_serial_are_separate_fields(self):
        self.assertTrue(self.workflow("11509"), self.messages)
        self.assertEqual([a for a in self.actions if a[0] == "replace"],
                         [("replace", 11, "11509"), ("replace", 12, "1234")])
        self.assertLess(self.actions.index(("select_all", 11)), self.actions.index(("replace", 11, "11509")))
        self.assertNotIn(("hotkey", ("ctrl", "a")), self.actions)
        self.assertEqual(self.values, {11: "11509", 12: "1234"})
        self.assertEqual(self.actions.count(("hotkey", ("alt", "o"))), 1)
        self.assertNotIn(("press", "enter"), self.actions)

    def test_rejected_month_stops_before_serial_or_confirmation(self):
        self.rejected.add(11)
        self.assertFalse(self.workflow("11509"))
        self.assertFalse(any(a[0] == "replace" and a[1] == 12 for a in self.actions))
        self.assertNotIn(("press", "enter"), self.actions)
        self.assertNotIn(("hotkey", ("alt", "o")), self.actions)

    def test_rejected_serial_stops_before_confirmation(self):
        self.rejected.add(12)
        self.assertFalse(self.workflow())
        self.assertNotIn(("press", "enter"), self.actions)
        self.assertNotIn(("hotkey", ("alt", "o")), self.actions)

    def test_failed_selection_does_not_write_or_confirm(self):
        self.reject_selection.add(11)
        self.assertFalse(self.workflow("11509"))
        self.assertFalse(any(a[0] == "replace" for a in self.actions))
        self.assertEqual(self.values[11], "11510")
        self.assertNotIn(("hotkey", ("alt", "o")), self.actions)

    def test_damaged_month_is_replaced_and_serial_keeps_leading_zeros(self):
        self.values = {11: "1151", 12: "9999"}
        self.assertTrue(self.engine._run_single_workflow("01150900010", self.messages.append, "11509"))
        self.assertEqual(self.values, {11: "11509", 12: "0010"})

    def test_matching_serial_still_blurs_and_revalidates_month(self):
        self.values[12] = "1234"
        original_click = self.click
        def blur_changes_month(x=None, y=None):
            original_click(x, y)
            if self.focus == 12:
                self.values[11] = "11510"
        with patch.object(module.pyautogui, "click", side_effect=blur_changes_month):
            self.assertFalse(self.workflow("11509"))
        self.assertNotIn(("hotkey", ("alt", "o")), self.actions)

    def test_cancel_after_select_all_does_not_write(self):
        original_message = self.control_message
        def cancel(hwnd, message, wparam=0, lparam=0):
            result = original_message(hwnd, message, wparam, lparam)
            if message == module.win32con.EM_SETSEL:
                self.engine.stop_event.set()
            return result
        with patch.object(self.engine, "_send_control_message", side_effect=cancel):
            self.assertFalse(self.workflow("11509"))
        self.assertFalse(any(a[0] == "replace" for a in self.actions))
        self.assertNotIn(("hotkey", ("alt", "o")), self.actions)

    def test_foreign_control_is_rejected_before_writing(self):
        with patch.object(module.win32gui, "IsChild", return_value=False):
            self.assertFalse(self.workflow("11509"))
        self.assertFalse(any(a[0] == "replace" for a in self.actions))

    def test_main_window_is_not_accepted_as_f10(self):
        self.popup.title = "調劑作業"
        self.assertIsNone(self.engine._read_popup_fields(self.popup, self.messages.append))

    def test_selector_ignores_main_window_and_rejects_multiple_dialogs(self):
        main = SimpleNamespace(title="調劑作業", _hWnd=200, activate=Mock())
        real_wait = module.AutomationEngine._wait_for_input_popup
        with patch.object(module.gw, "getAllWindows", return_value=[main, self.popup]):
            self.assertIs(real_wait(self.engine, self.messages.append), self.popup)
        main.activate.assert_not_called()
        with patch.object(module.gw, "getAllWindows", return_value=[self.popup, self.popup]):
            self.assertIsNone(real_wait(self.engine, self.messages.append))


if __name__ == "__main__":
    unittest.main(verbosity=2)
