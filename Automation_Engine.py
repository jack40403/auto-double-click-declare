import pyautogui
import time
import keyboard
import threading
from Vision_Helper import VisionHelper
import pygetwindow as gw
import win32gui
import win32con
import win32com.client
import re
import os
import json
import numpy as np
import ctypes
from ctypes import wintypes
import logging

F10_BUILD = "F10-20261002.4"

class AutomationEngine:
    def __init__(self, vision_helper):
        self.vision_helper = vision_helper
        self.is_running = False
        self.stop_event = threading.Event()
        self.fixed_pos = None # 記憶的手動座標
        
        # 設定基礎延遲
        pyautogui.PAUSE = 0.5
        pyautogui.FAILSAFE = True
        
        self.task_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "current_task.json")

    def _focus_window(self, status_callback):
        """改為僅依賴手動座標進行點擊聚焦"""
        if self.fixed_pos:
            try:
                # 點擊手動座標以確保該視窗被帶到最上層
                pyautogui.click(self.fixed_pos[0], self.fixed_pos[1])
                time.sleep(0.3)
                return True
            except:
                pass
        return False

    def _wait_for_input_popup(self, status_callback, timeout=10):
        """等待輸入視窗彈出 (時間延長至 10 秒)"""
        start_time = time.time()
        status_callback(f"等待輸入視窗彈出 (最長 {timeout} 秒)...")
        while time.time() - start_time < timeout:
            if self.stop_event.is_set(): return False
            
            # F10 的目標已由實際畫面確認；不能把「調劑作業」主視窗當成彈窗。
            matches = [
                w for w in gw.getAllWindows()
                if self._normalize_popup_label(w.title) == "銷售修改"
                and win32gui.IsWindowVisible(w._hWnd)
            ]
            if len(matches) == 1:
                w = matches[0]
                try:
                    if w.isMinimized:
                        w.restore()
                    w.activate()
                    time.sleep(0.5)
                    status_callback(f"偵測到彈出視窗: {w.title} ({w.left}, {w.top})")
                    return w
                except Exception:
                    logging.exception("無法啟用 F10 銷售修改視窗")
            elif len(matches) > 1:
                status_callback("同時找到多個「銷售修改」視窗，無法確認目標。")
                return None
            time.sleep(0.3)
        return None

    def _extract_serials(self, file_path, status_callback):
        """從藥品健保價欄位回找所屬的錯誤序號，並依序號去重。"""
        status_callback(f"正在分析文件: {os.path.basename(file_path)}...")
        try:
            serial_pattern = re.compile(r"(?<![A-Za-z0-9])([0-9]{4,11})(?![A-Za-z0-9])")
            error_label_pattern = re.compile(r"錯誤\s*(?:處方\s*)?序號")
            medicine_field_pattern = re.compile(
                r"\b[A-Z]{2}[0-9]{8}\b.*?健保價", re.IGNORECASE
            )
            declaration_error_pattern = re.compile(r"申報金額\s*交叉\s*不平衡")
            serials = []
            chunks = []
            table_has_error_column = False

            if file_path.lower().endswith(('.html', '.htm')):
                from bs4 import BeautifulSoup
                with open(file_path, 'rb') as f:
                    raw_content = f.read()

                charset = re.search(
                    br"charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)",
                    raw_content[:4096],
                    re.IGNORECASE,
                )
                encodings = []
                if charset:
                    declared = charset.group(1).decode('ascii', errors='ignore').lower()
                    encodings.append('cp950' if declared in ('big5', 'big5-hkscs', 'ms950') else declared)
                encodings.extend(('utf-8-sig', 'cp950'))

                content = None
                for encoding in dict.fromkeys(encodings):
                    try:
                        content = raw_content.decode(encoding)
                        break
                    except (LookupError, UnicodeDecodeError):
                        continue
                if content is None:
                    raise UnicodeDecodeError('cp950', raw_content, 0, len(raw_content), 'unable to decode report')

                soup = BeautifulSoup(content, 'html.parser')
                for table in soup.find_all('table'):
                    rows = table.find_all('tr')
                    error_column_index = None

                    for row in rows:
                        cells = row.find_all(['th', 'td'], recursive=False)
                        for index, cell in enumerate(cells):
                            if error_label_pattern.search(cell.get_text(' ', strip=True)):
                                error_column_index = index
                                break
                        if error_column_index is not None:
                            break

                    if error_column_index is None:
                        continue

                    table_has_error_column = True
                    for row in rows:
                        cells = row.find_all(['th', 'td'], recursive=False)
                        if error_column_index >= len(cells):
                            continue
                        row_text = row.get_text(' ', strip=True)
                        if not (
                            medicine_field_pattern.search(row_text)
                            or declaration_error_pattern.search(row_text)
                        ):
                            continue

                        error_serial = cells[error_column_index].get_text(' ', strip=True)
                        if error_serial.isdigit() and 4 <= len(error_serial) <= 11:
                            serials.append(error_serial)

                if not table_has_error_column:
                    rows = soup.find_all('tr')
                    if rows:
                        chunks = [row.get_text(' ', strip=True) for row in rows]
                    else:
                        paragraphs = soup.find_all('p')
                        if paragraphs:
                            chunks = [paragraph.get_text(' ', strip=True) for paragraph in paragraphs]
                        else:
                            divs = soup.find_all('div')
                            leaf_divs = [div for div in divs if not div.find('div')]
                            chunks = [div.get_text(' ', strip=True) for div in leaf_divs]
                            if not chunks:
                                chunks = [soup.get_text(' ', strip=True)]
            else:
                try:
                    with open(file_path, 'r', encoding='utf-8-sig') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    with open(file_path, 'r', encoding='cp950') as f:
                        content = f.read()
                chunks = content.splitlines()

            if chunks:
                # 舊版輸出的一行一個純數字序號檔仍可直接讀取。
                non_empty_chunks = [chunk.strip() for chunk in chunks if chunk.strip()]
                if non_empty_chunks and all(
                    chunk.isdigit() and 4 <= len(chunk) <= 11
                    for chunk in non_empty_chunks
                ):
                    serials.extend(non_empty_chunks)
                else:
                    current_error_serial = None
                    waiting_for_error_serial = False

                    for chunk in chunks:
                        text = chunk.strip()
                        if not text:
                            continue

                        medicine_match = medicine_field_pattern.search(text)
                        declaration_error_match = declaration_error_pattern.search(text)
                        target_match = medicine_match or declaration_error_match
                        error_label = error_label_pattern.search(text)

                        if error_label:
                            # 標籤與序號同一列時取標籤後的數字；若序號在前，取標籤前最近的數字。
                            before_medicine = text[:medicine_match.start()] if medicine_match else text
                            after_label = before_medicine[error_label.end():]
                            candidates = serial_pattern.findall(after_label)
                            if not candidates:
                                candidates = serial_pattern.findall(before_medicine[:error_label.start()])

                            if candidates:
                                current_error_serial = candidates[-1]
                                waiting_for_error_serial = False
                            else:
                                current_error_serial = None
                                waiting_for_error_serial = True
                        elif waiting_for_error_serial and text.isdigit() and 4 <= len(text) <= 11:
                            current_error_serial = text
                            waiting_for_error_serial = False

                        if target_match and current_error_serial and not waiting_for_error_serial:
                            serials.append(current_error_serial)

            # 同一個錯誤序號可能對應多個藥品欄位，只保留一次並維持出現順序。
            result = list(dict.fromkeys(serials))
            status_callback(f"提取完成，共發現 {len(result)} 個待處理錯誤序號。")
            return result
        except Exception as e:
            status_callback(f"解析文件失敗: {e}")
            return []

    def process_report_html(self, input_path, output_path, status_callback):
        """專門用於將 HTML 報表轉換為序號清單檔案"""
        try:
            serials = self._extract_serials(input_path, status_callback)
            if not serials:
                status_callback("未在報表中找到合格的序號。")
                return False
            
            with open(output_path, 'w', encoding='utf-8') as f:
                for sn in serials:
                    f.write(f"{sn}\n")
            
            status_callback(f"已成功產生序號文檔: {os.path.basename(output_path)}")
            return True
        except Exception as e:
            status_callback(f"儲存序號文檔失敗: {e}")
            return False

    def _save_progress(self, serials):
        with open(self.task_file, 'w', encoding='utf-8') as f:
            json.dump(serials, f)

    def process_document(self, file_path, status_callback, sales_month="11510"):
        self.stop_event.clear()
        self.is_running = True
        
        try:
            if not isinstance(sales_month, str) or not re.fullmatch(r"[0-9]{3}(0[1-9]|1[0-2])", sales_month):
                status_callback("銷售月份格式錯誤：請輸入民國年月五碼，例如 11510。")
                return

            # 優先檢查是否有舊任務
            serial_numbers = []
            if not file_path and os.path.exists(self.task_file):
                with open(self.task_file, 'r', encoding='utf-8') as f:
                    serial_numbers = json.load(f)
                status_callback(f"延續上次未完成任務: 剩餘 {len(serial_numbers)} 筆")
            elif file_path:
                serial_numbers = self._extract_serials(file_path, status_callback)
                self._save_progress(serial_numbers)

            if not serial_numbers:
                status_callback("無待處理序號。")
                return

            self._focus_window(status_callback)
            
            # 開始掃描
            total = len(serial_numbers)
            while serial_numbers:
                if self.stop_event.is_set(): break
                
                sn = serial_numbers[0]
                status_callback(f"--- 正在處理 (剩餘 {len(serial_numbers)} 筆): {sn} ---")
                
                # 執行單個流程
                completed = self._run_single_workflow(sn, status_callback, sales_month)
                if not completed:
                    break
                
                # 執行成功後移除並存檔 (假設執行完就算成功，或可依照需求細分)
                serial_numbers.pop(0)
                self._save_progress(serial_numbers)
                
            if not serial_numbers:
                status_callback(">>> 所有作業已完成 <<<")
                if os.path.exists(self.task_file): os.remove(self.task_file)
            else:
                status_callback(">>> 自動化已暫停，進度已儲存 <<<")

        except Exception as e:
            status_callback(f"錯誤: {str(e)}")
        finally:
            self.is_running = False

    @staticmethod
    def _normalize_popup_label(text):
        return re.sub(r"[\s:：,，.。]", "", text or "")

    @staticmethod
    def _send_control_message(hwnd, message, wparam=0, lparam=0):
        """以有逾時的 Win32 訊息操作指定控制項，不經過鍵盤或輸入法。"""
        result = ctypes.c_size_t()
        send = ctypes.windll.user32.SendMessageTimeoutW
        send.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
        ]
        send.restype = wintypes.LPARAM
        if not send(hwnd, message, wparam, lparam,
                    win32con.SMTO_ABORTIFHUNG | win32con.SMTO_BLOCK, 500, ctypes.byref(result)):
            raise OSError(f"控制項未回應或拒絕存取 (message=0x{message:04X})")
        return result.value

    @staticmethod
    def _read_edit_text(hwnd):
        """GetWindowText 不保證能讀到其他程序的 Edit，改以 WM_GETTEXT 讀值。"""
        buffer = ctypes.create_unicode_buffer(256)
        try:
            AutomationEngine._send_control_message(
                hwnd, win32con.WM_GETTEXT, len(buffer), ctypes.addressof(buffer))
            return buffer.value
        except OSError:
            return win32gui.GetWindowText(hwnd)

    def _replace_edit_text(self, hwnd, value):
        """確認已全選後以 WM_SETTEXT 整欄覆寫，保留前導零並立即讀回。"""
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4,5}", value):
            raise ValueError("欄位只能寫入四碼或五碼半形數字")
        if self.stop_event.is_set():
            raise InterruptedError("作業已停止")
        previous = self._read_edit_text(hwnd)
        self._send_control_message(hwnd, win32con.EM_SETSEL, 0, -1)
        selection_start, selection_end = ctypes.c_uint32(), ctypes.c_uint32()
        self._send_control_message(
            hwnd, win32con.EM_GETSEL,
            ctypes.addressof(selection_start), ctypes.addressof(selection_end))
        if (selection_start.value, selection_end.value) != (0, len(previous)):
            raise RuntimeError("無法確認欄位文字已全部選取，未寫入新值")
        if self.stop_event.is_set():
            raise InterruptedError("作業已停止")
        # 整欄覆寫使用 WM_SETTEXT；不送 Ctrl+A、Backspace 或數字按鍵。
        buffer = ctypes.create_unicode_buffer(value)
        if not self._send_control_message(hwnd, win32con.WM_SETTEXT, 0, ctypes.addressof(buffer)):
            raise RuntimeError("欄位拒絕覆寫")
        actual = self._read_edit_text(hwnd)
        if actual != value:
            raise RuntimeError(f"覆寫後讀回 {actual!r}，預期 {value!r}")
        return True

    def _focus_popup_field(self, popup, field):
        """重新確認輸入框仍屬於此彈窗，再切換焦點以觸發原程式的欄位驗證。"""
        if self.stop_event.is_set():
            raise InterruptedError("作業已停止")
        hwnd = field["hwnd"]
        if (
            not win32gui.IsWindow(popup._hWnd) or not win32gui.IsWindow(hwnd)
            or self._normalize_popup_label(win32gui.GetWindowText(popup._hWnd)) != "銷售修改"
            or not win32gui.IsChild(popup._hWnd, hwnd)
            or not win32gui.IsWindowVisible(hwnd) or not win32gui.IsWindowEnabled(hwnd)
            or not any(token in win32gui.GetClassName(hwnd).lower() for token in ("edit", "textbox"))
            or win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & win32con.ES_READONLY
        ):
            raise RuntimeError("輸入框已失效或無法編輯")
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        pyautogui.click((left + right) // 2, (top + bottom) // 2)
        time.sleep(0.15)
        if self.stop_event.is_set():
            raise InterruptedError("作業已停止")
        return hwnd

    def _write_popup_field(self, popup, field, value, label, status_callback):
        try:
            pattern = r"[0-9]{3}(0[1-9]|1[0-2])" if label == "銷售月份" else r"[0-9]{4}"
            if not re.fullmatch(pattern, value):
                raise ValueError(f"{label}格式錯誤")
            hwnd = self._focus_popup_field(popup, field)
            self._replace_edit_text(hwnd, value)
            status_callback(f"{label}已全選覆寫並讀回確認：{value}")
            return not self.stop_event.is_set()
        except InterruptedError:
            status_callback("已停止，保留目前待處理序號。")
            return False
        except Exception as e:
            logging.exception("F10 欄位覆寫失敗：%s", label)
            status_callback(f"!!! {label}覆寫失敗：{e}；停止並保留此筆序號。")
            self.stop()
            return False

    @staticmethod
    def _aligned_popup_fields(edits):
        """只接受兩個同行寬度、上下排列的輸入框；月份值會另外校驗。"""
        if len(edits) != 2:
            return None
        upper, lower = sorted(edits, key=lambda field: field["rect"][1])
        left, top, right, bottom = upper["rect"]
        sl, st, sr, sb = lower["rect"]
        tolerance = max(6, (right - left) * 0.1)
        if (
            abs(left - sl) <= tolerance and abs(right - sr) <= tolerance
            and bottom <= st and st - bottom <= 3 * (bottom - top)
            and 0.5 <= (sb - st) / max(1, bottom - top) <= 2
        ):
            return upper, lower
        return None

    def _read_popup_fields(self, popup, status_callback, verify_serial=False):
        """讀取 F10 月份與序號欄；視窗控制項標籤不可讀時改以 OCR 配對。"""
        try:
            if self._normalize_popup_label(popup.title) != "銷售修改":
                status_callback("目前不是「銷售修改」視窗，停止欄位辨識。")
                return None
            controls = []

            def collect(hwnd, _extra):
                try:
                    if not win32gui.IsWindowVisible(hwnd):
                        return True
                    rect = win32gui.GetWindowRect(hwnd)
                    class_name = win32gui.GetClassName(hwnd)
                    is_edit = any(token in class_name.lower() for token in ("edit", "textbox"))
                    if rect[2] > rect[0] and rect[3] > rect[1]:
                        controls.append({
                            "hwnd": hwnd,
                            "class": class_name,
                            "text": self._read_edit_text(hwnd) if is_edit else win32gui.GetWindowText(hwnd),
                            "rect": rect,
                            "editable": is_edit and bool(win32gui.IsWindowEnabled(hwnd)),
                        })
                except win32gui.error:
                    pass
                return True

            win32gui.EnumChildWindows(popup._hWnd, collect, None)
            edits = [
                c for c in controls
                if c["editable"]
            ]

            def control_label(terms):
                labels = [
                    c for c in controls
                    if any(term in self._normalize_popup_label(c["text"]) for term in terms)
                ]
                return labels[0]["rect"] if len(labels) == 1 else None

            def field_for_rect(label_rect):
                if not label_rect:
                    return None
                lx1, ly1, lx2, ly2 = label_rect
                label_y = (ly1 + ly2) / 2
                candidates = []
                for edit in edits:
                    fx1, fy1, fx2, fy2 = edit["rect"]
                    edit_y = (fy1 + fy2) / 2
                    if fx1 >= lx2 and abs(edit_y - label_y) <= 24:
                        candidates.append((abs(edit_y - label_y), fx1 - lx2, edit))
                # OCR 偶爾會把欄位內的值併入標籤框，改用同行且位於標籤右側的控制項。
                if not candidates:
                    label_center_x = (lx1 + lx2) / 2
                    for edit in edits:
                        fx1, fy1, fx2, fy2 = edit["rect"]
                        edit_y = (fy1 + fy2) / 2
                        edit_center_x = (fx1 + fx2) / 2
                        if edit_center_x > label_center_x and abs(edit_y - label_y) <= 28:
                            candidates.append((abs(edit_y - label_y), abs(edit_center_x - label_center_x), edit))
                if not candidates:
                    return None
                candidates.sort(key=lambda item: (item[0], item[1]))
                if len(candidates) > 1 and candidates[0][0] == candidates[1][0] and candidates[0][1] == candidates[1][1]:
                    return None
                return candidates[0][2]

            month = field_for_rect(control_label(("銷售月份",)))
            serial = field_for_rect(control_label(("序號",)))
            ocr_items = None

            def read_popup_ocr():
                nonlocal ocr_items
                if ocr_items is not None:
                    return ocr_items
                ocr_items = []
                try:
                    screen_width, screen_height = pyautogui.size()
                    left = max(0, popup.left)
                    top = max(0, popup.top)
                    right = min(screen_width, popup.left + popup.width)
                    bottom = min(screen_height, popup.top + popup.height)
                    if right <= left or bottom <= top:
                        return ocr_items
                    image = pyautogui.screenshot(region=(left, top, right - left, bottom - top))
                    # 小字先放大；EasyOCR 不接受 PyAutoGUI 傳回的 PIL.Image。
                    scale = 2
                    pixels = np.asarray(image.convert("RGB").resize((image.width * scale, image.height * scale)))
                    for bbox, text, confidence in self.vision_helper.reader.readtext(pixels, detail=1):
                        xs = [point[0] for point in bbox]
                        ys = [point[1] for point in bbox]
                        ocr_items.append({
                            "text": text,
                            "confidence": confidence,
                            "rect": (
                                int(min(xs) / scale + left), int(min(ys) / scale + top),
                                int(max(xs) / scale + left), int(max(ys) / scale + top),
                            ),
                        })
                except Exception as e:
                    logging.exception("F10 OCR 失敗")
                    status_callback(f"F10 標籤 OCR 辨識失敗：{e}")
                return ocr_items

            def ocr_number(field):
                left, top, right, bottom = field["rect"]
                values = set()
                for item in read_popup_ocr():
                    x1, y1, x2, y2 = item["rect"]
                    candidate = re.sub(r"\s+", "", item["text"])
                    if (
                        left <= (x1 + x2) / 2 <= right
                        and top <= (y1 + y2) / 2 <= bottom
                        and item["confidence"] >= 0.25
                        and re.fullmatch(r"[0-9]+", candidate)
                    ):
                        values.add(candidate)
                return next(iter(values)) if len(values) == 1 else ""

            def ocr_label_rect(term):
                items = [
                    item for item in read_popup_ocr()
                    if item["confidence"] >= 0.15
                ]
                direct = [
                    item for item in items
                    if term in self._normalize_popup_label(item["text"])
                ]
                if direct:
                    direct.sort(key=lambda item: item["confidence"], reverse=True)
                    return direct[0]["rect"]

                # 中文標籤可能被 OCR 拆成相鄰字詞，例如「銷售」和「月份」或「序」和「號」。
                rows = []
                for item in sorted(items, key=lambda value: (value["rect"][1], value["rect"][0])):
                    x1, y1, x2, y2 = item["rect"]
                    center_y = (y1 + y2) / 2
                    row = next(
                        (candidate for candidate in rows
                         if abs(candidate["center_y"] - center_y) <= max(12, (y2 - y1) // 2)),
                        None,
                    )
                    if row is None:
                        row = {"center_y": center_y, "items": []}
                        rows.append(row)
                    row["items"].append(item)

                matches = []
                for row in rows:
                    row_items = sorted(row["items"], key=lambda value: value["rect"][0])
                    for start in range(len(row_items)):
                        combined = ""
                        selected = []
                        previous_right = None
                        for item in row_items[start:start + 4]:
                            x1, y1, x2, y2 = item["rect"]
                            if previous_right is not None and x1 - previous_right > 28:
                                break
                            combined += self._normalize_popup_label(item["text"])
                            selected.append(item)
                            previous_right = x2
                            if term in combined:
                                matches.append({
                                    "rect": (
                                        min(value["rect"][0] for value in selected),
                                        min(value["rect"][1] for value in selected),
                                        max(value["rect"][2] for value in selected),
                                        max(value["rect"][3] for value in selected),
                                    ),
                                    "confidence": min(value["confidence"] for value in selected),
                                })
                                break
                if not matches:
                    return None
                matches.sort(key=lambda item: item["confidence"], reverse=True)
                return matches[0]["rect"]

            if not month or not serial or month["hwnd"] == serial["hwnd"]:
                # 此特定視窗只有兩個對齊的輸入框；舊輸入失敗留下的短碼／亂碼也可修復。
                aligned = self._aligned_popup_fields(edits)
                if aligned:
                    upper, lower = aligned
                    month_value = re.sub(r"\s+", "", upper["text"])
                    if not month_value:
                        month_value = ocr_number(upper)
                    month, serial = dict(upper, text=month_value), lower
                    status_callback(f"已確認 F10 兩個輸入框：上方月份 {month_value!r}、下方序號。")

            if not month or not serial or month["hwnd"] == serial["hwnd"]:
                month_label_rect = ocr_label_rect("銷售月份")
                serial_label_rect = ocr_label_rect("序號")
                if month_label_rect and serial_label_rect and len(edits) >= 2:
                    month = field_for_rect(month_label_rect)
                    serial = field_for_rect(serial_label_rect)
                    if month and serial and month["hwnd"] != serial["hwnd"]:
                        status_callback("F10 標籤控制項無法讀取，已改用畫面 OCR 配對月份與序號欄。")

            if not month or not serial or month["hwnd"] == serial["hwnd"]:
                logging.warning("F10 配對失敗：controls=%s, ocr_labels=%s",
                                [{"class": c["class"], "rect": c["rect"],
                                  "text_length": len(c["text"]), "editable": c["editable"]} for c in controls],
                                [item["text"] for item in (ocr_items or []) if not item["text"].isdigit()])
                status_callback(
                    f"無法明確配對 F10 月份與序號欄（輸入框 {len(edits)} 個；"
                    f"月份/序號標籤控制項 {'可讀' if control_label(('銷售月份',)) and control_label(('序號',)) else '不可讀'}）。"
                )
                return None

            def describe(field, need_value):
                left, top, right, bottom = field["rect"]
                value = re.sub(r"\s+", "", field["text"] or "")
                if not value and need_value:
                    value = ocr_number(field)
                return {
                    "hwnd": field["hwnd"],
                    "value": value,
                    "position": ((left + right) // 2, (top + bottom) // 2),
                }

            # 序號原本可為空白；只有輸入後讀回仍為空時才需要 OCR 複核。
            return {"month": describe(month, True), "serial": describe(serial, verify_serial)}
        except Exception as e:
            logging.exception("讀取 F10 欄位失敗")
            status_callback(f"讀取 F10 月份與序號欄位失敗：{e}")
            return None

    def _run_single_workflow(self, sn, status_callback, sales_month="11510"):
        # Step 0: 強勢點擊視窗以確保焦點 (改用手動座標)
        if self.fixed_pos:
            status_callback("0. 點擊校準座標以聚焦視窗")
            pyautogui.click(self.fixed_pos[0], self.fixed_pos[1])
            time.sleep(0.3)
            # 點兩下確保正確鎖定視窗焦點
            pyautogui.click(self.fixed_pos[0], self.fixed_pos[1]) 
            time.sleep(0.8)
        else:
            status_callback("!!! 錯誤: 尚未設定點擊位置，請先執行手動校準。")
            self.stop()
            return False

        # Step 1: F10
        status_callback("1. 按下 F10")
        pyautogui.press('f10')
        
        # 偵測彈窗
        popup = self._wait_for_input_popup(status_callback)
        if popup:
            # 依標籤辨識兩個欄位，分別比對後再輸入。
            short_sn = sn[-4:]
            status_callback("2. 辨識 F10 的銷售月份與序號輸入欄...")
            fields = self._read_popup_fields(popup, status_callback)
            if not fields:
                status_callback("!!! 無法確認月份欄與序號欄；停止並保留此筆序號。")
                self.stop()
                return False

            current_month = fields["month"]["value"]
            if current_month == sales_month:
                status_callback(f"銷售月份已是 {sales_month}，不更改。")
            else:
                status_callback(f"銷售月份 {current_month} 與設定不同，更新為 {sales_month}...")
                if not self._write_popup_field(popup, fields["month"], sales_month, "銷售月份", status_callback):
                    return False

            if current_month != sales_month:
                updated_fields = self._read_popup_fields(popup, status_callback)
                if not updated_fields or updated_fields["month"]["value"] != sales_month:
                    status_callback("!!! 銷售月份修改後校驗失敗；停止並保留此筆序號。")
                    self.stop()
                    return False

            fields = updated_fields if current_month != sales_month else fields
            current_serial = fields["serial"]["value"]
            if current_serial == short_sn:
                status_callback(f"序號欄已是 {short_sn}，不重複輸入。")
                try:
                    self._focus_popup_field(popup, fields["serial"])
                except InterruptedError:
                    return False
                except Exception as e:
                    status_callback(f"!!! 無法切換至序號欄：{e}")
                    self.stop()
                    return False
            else:
                status_callback(f"切換至序號欄，輸入末四位 {short_sn}...")
                if not self._write_popup_field(popup, fields["serial"], short_sn, "序號", status_callback):
                    return False

            # 切到序號欄後，月份的 LostFocus 驗證可能再改值；送出前重新確認兩欄。
            if self.stop_event.is_set():
                return False
            verified_fields = self._read_popup_fields(popup, status_callback, verify_serial=True)
            if (not verified_fields or verified_fields["serial"]["value"] != short_sn
                    or verified_fields["month"]["value"] != sales_month):
                status_callback("!!! 序號或月份輸入後校驗失敗；停止並保留此筆序號。")
                self.stop()
                return False
            
            time.sleep(0.3)
            
            # 只送一次「確定」快捷鍵，避免彈窗關閉後又把第二次確認送到主視窗。
            if self.stop_event.is_set():
                return False
            pyautogui.hotkey('alt', 'o')
            
            time.sleep(1.2)
        else:
            status_callback("!!! 未偵測到 F10 視窗，月份與序號未輸入；停止以保留目前序號。")
            self.stop()
            return False
        
        # Step 3: 定位並連點日期
        pos = self.fixed_pos
        if not pos:
            status_callback("正在透過畫面辨識搜尋「調劑日期」欄位...")
            pos = self.vision_helper.find_text_position("調劑日期")
            
        if pos:
            status_callback(f"3. 點擊日期欄位 {pos}")
            pyautogui.moveTo(pos[0], pos[1], duration=0.2)
            # 輔助：先點一下確保輸入焦點，再雙擊
            pyautogui.click()
            time.sleep(0.2)
            pyautogui.doubleClick()
            time.sleep(0.8)
            
            # Step 4: F9
            status_callback("4. 按下 F9")
            pyautogui.press('f9')
            time.sleep(1.2) # 等待彈窗出現
            
            # Step 5: 點擊否
            status_callback("5. 處理彈窗：點擊「否」(N)")
            pyautogui.press('n')
            time.sleep(0.5)
            
            # Step 6: ALT + E
            status_callback("6. 存檔離開：按下 ALT + E")
            pyautogui.hotkey('alt', 'e')
            time.sleep(1.0)
        else:
            status_callback("!!! 停止作業：找不到「調劑日期」位置。")
            status_callback("建議：請先按「2. 設定點擊位置」手動校準日期欄位座標。")
            self.stop()
            return False

        return True

    def stop(self):
        self.stop_event.set()
        self.is_running = False
