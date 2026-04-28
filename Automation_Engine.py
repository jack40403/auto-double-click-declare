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
            
            # 獲取所有視窗
            all_wins = gw.getAllWindows()
            for w in all_wins:
                # 偵測對話框視窗 (寬度通常小於 1000)
                # 排除座標不合理的視窗 (如最小化的視窗座標常在 -32000)
                if 0 < w.width < 1000 and w.left > -1000 and w.top > -1000:
                    # 排除自己這支程式 (更加嚴格的排除邏輯)
                    if "自動化" in w.title or "助手" in w.title or "Engine" in w.title: continue
                    
                    # 擴展關鍵字以增加相容性
                    titles = ["序號", "查詢", "輸入", "作業", "處理", "銷售", "修改", "請輸入"]
                    if any(t in w.title for t in titles):
                        status_callback(f"偵測到彈出視窗: {w.title} ({w.left}, {w.top})")
                        try:
                            if w.isMinimized: w.restore()
                            w.activate()
                            time.sleep(0.5) 
                            return w 
                        except: pass
            time.sleep(0.3)
        return None

    def _extract_serials(self, file_path, status_callback):
        """從 HTML 或 TXT 提取包含「健保價」的序號"""
        status_callback(f"正在分析文件: {os.path.basename(file_path)}...")
        serials = []
        try:
            if file_path.lower().endswith(('.html', '.htm')):
                from bs4 import BeautifulSoup
                # 優先嘗試 cp950 (Big5)，台灣醫療常用的編碼
                try:
                    with open(file_path, 'r', encoding='cp950', errors='ignore') as f:
                        content = f.read()
                except:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                soup = BeautifulSoup(content, 'html.parser')
                # 搜尋包含「健保價」的文字區塊
                elements = soup.find_all(['tr', 'p', 'div'])
                for el in elements:
                    txt = el.get_text()
                    if "健保價" in txt:
                        # 提取序號 (通常為 4 到 11 位數字)
                        nums = re.findall(r'\d{4,11}', txt)
                        for n in nums: 
                            # 只要四位數 (個十百千)
                            serials.append(n[-4:])
            else:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line: continue
                        
                        # 如果是乾淨的序號檔 (純數字)，直接加入
                        if line.isdigit() and 4 <= len(line) <= 11:
                            serials.append(line[-4:])
                        # 如果是原始報表文字，則搜尋關鍵字
                        elif "健保價" in line:
                            nums = re.findall(r'\d{4,11}', line)
                            for n in nums: serials.append(n[-4:])
            
            # 去重並維持順序
            result = list(dict.fromkeys(serials))
            status_callback(f"提取完成，共發現 {len(result)} 個待處理序號。")
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

    def process_document(self, file_path, status_callback):
        self.stop_event.clear()
        self.is_running = True
        
        try:
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
                self._run_single_workflow(sn, status_callback)
                
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

    def _run_single_workflow(self, sn, status_callback):
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
            return

        # Step 1: F10
        status_callback("1. 按下 F10")
        pyautogui.press('f10')
        
        # 偵測彈窗
        popup = self._wait_for_input_popup(status_callback)
        if popup:
            # Step 2: 回歸最一般的輸入方式 (非九宮格)
            short_sn = sn[-4:]
            click_x = popup.left + popup.width // 2
            click_y = popup.top + popup.height // 2 + 40
            status_callback(f"2. 點擊輸入框後輸入 {short_sn}...")
            
            pyautogui.click(click_x, click_y)
            time.sleep(0.8)
            
            # 清空欄位
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('backspace')
            time.sleep(0.1)
            
            # 直接打字 (最快的方式)
            pyautogui.write(short_sn)
            
            time.sleep(0.3)
            
            # 按下確定
            pyautogui.press('enter')
            pyautogui.hotkey('alt', 'o')
            
            time.sleep(1.2)
        else:
            status_callback("警告：未偵測到輸入彈窗，嘗試直接按 Alt+O 並繼續...")
            pyautogui.hotkey('alt', 'o')
            time.sleep(1.5)
        
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

    def stop(self):
        self.stop_event.set()
        self.is_running = False
