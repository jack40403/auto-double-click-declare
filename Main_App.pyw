import os
import sys
import logging

# 設定日誌以便除錯
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_log.txt")
logging.basicConfig(filename=log_file, level=logging.DEBUG, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("程式啟動中...")

try:
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import filedialog, messagebox
    import threading
    import pyautogui
    import keyboard
    from Automation_Engine import AutomationEngine
    from Vision_Helper import VisionHelper
    import ctypes
except Exception as e:
    logging.error(f"匯入模組失敗: {e}", exc_info=True)
    import traceback
    traceback.print_exc()
    input(f"\n[嚴重錯誤] 程式啟動失敗，模組無法匯入: {e}\n請拍下這個畫面並按 Enter 離開...")
    sys.exit(1)

# 設定主題
try:
    logging.info("設定系統主題與顏色...")
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
except Exception as e:
    logging.warning(f"CTK 主題設定失敗 (不影響執行): {e}")

class PharmacyApp(ctk.CTk):
    def __init__(self):
        logging.info("PharmacyApp 實例化...")
        super().__init__()
        
        # 標題與大小
        self.title("藥局調劑作業自動化助手 (手動校準版)")
        self.geometry("600x580")
        logging.info("視窗基礎參數設定完成。")

        # 狀態變數
        self.engine_ready = False
        self.file_path = ""
        self.manual_pos = None # 手動設定的座標

        # 配置 UI (先畫介面)
        logging.info("正在建構使用者介面元件...")
        self._setup_ui()
        logging.info("使用者介面元件建構完成。")
        
        # 異步初始化引擎以免視窗卡住
        logging.info("於背景啟動辨識引擎...")
        threading.Thread(target=self._init_engine, daemon=True).start()

    def _init_engine(self):
        try:
            self._log("正在檢查辨識引擎模型，這可能需要一點時間...")
            self.vision_helper = VisionHelper()
            self.engine = AutomationEngine(self.vision_helper)
            self.engine_ready = True
            self._log("辨識引擎已準備就緒，您可以開始操作了。")
            self.btn_start.configure(state="normal")
        except Exception as e:
            logging.error(f"引擎初始化失敗: {e}", exc_info=True)
            self._log(f"!!! 引擎啟動失敗: {e}")
            messagebox.showerror("錯誤", f"辨識引擎初始化失敗: {e}\n請檢查網路連線後重試。")

    def _setup_ui(self):
        # 標題
        self.label = ctk.CTkLabel(self, text="調劑作業自動化系統", font=("Microsoft JhengHei", 24, "bold"))
        self.label.pack(pady=15)

        # 1. 檔案選取區域
        self.file_frame = ctk.CTkFrame(self)
        self.file_frame.pack(pady=10, padx=20, fill="x")

        self.btn_select_file = ctk.CTkButton(self.file_frame, text="1. 選取序號文檔", command=self._select_file)
        self.btn_select_file.pack(side="left", padx=10, pady=10)

        self.btn_process_html = ctk.CTkButton(self.file_frame, text="0. 整理報表 (HTML 轉序號)", 
                                           fg_color="#3498DB", hover_color="#2980B9",
                                           command=self._process_html_report)
        self.btn_process_html.pack(side="left", padx=10, pady=10)

        self.lbl_file_path = ctk.CTkLabel(self.file_frame, text="尚未選取檔案", text_color="gray")
        self.lbl_file_path.pack(side="left", padx=10)

        # 2. 手動校準區域
        self.calib_frame = ctk.CTkFrame(self)
        self.calib_frame.pack(pady=10, padx=20, fill="x")
        
        self.btn_calibrate = ctk.CTkButton(self.calib_frame, text="2. 設定點擊位置", fg_color="orange", hover_color="#D35400", 
                                          command=self._start_calibration)
        self.btn_calibrate.pack(side="left", padx=10, pady=10)
        
        self.lbl_pos = ctk.CTkLabel(self.calib_frame, text="目前定位：自動辨識", text_color="yellow")
        self.lbl_pos.pack(side="left", padx=10)

        # 狀態顯示區
        self.textbox = ctk.CTkTextbox(self, width=560, height=180)
        self.textbox.pack(pady=10, padx=20)
        self.textbox.insert("0.0", "【使用說明】\n1. 選取序號文檔。\n2. 若自動定位不到，請按「設定點擊位置」，將滑鼠移到「調劑日期」欄位上方並按 Ctrl。\n3. 點擊「開始執行」。\n")

        # 控制按鈕區域
        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(pady=20)

        self.btn_start = ctk.CTkButton(self.btn_frame, text="開始執行", fg_color="green", hover_color="darkgreen", 
                                      command=self._start_automation, state="disabled")
        self.btn_start.pack(side="left", padx=10)

        self.btn_stop = ctk.CTkButton(self.btn_frame, text="立即停止", fg_color="red", hover_color="darkred",
                                     command=self._stop_automation)
        self.btn_stop.pack(side="left", padx=10)

    def _start_calibration(self):
        self._log("請將滑鼠移動到「調劑日期」欄位位置，然後按下 Ctrl 鍵...")
        self.btn_calibrate.configure(text="等待 Ctrl 中...", state="disabled")
        
        def wait_for_ctrl():
            while True:
                if keyboard.is_pressed('ctrl'):
                    x, y = pyautogui.position()
                    self.manual_pos = (x, y)
                    # 更新自動化引擎的座標
                    self.engine.fixed_pos = self.manual_pos
                    self.lbl_pos.configure(text=f"定位座標：({x}, {y})", text_color="#2ECC71")
                    self._log(f"校準成功！已記錄座標：({x}, {y})")
                    self.btn_calibrate.configure(text="2. 重新設定位置", state="normal")
                    break
                if self.engine.stop_event.is_set():
                    break
                tk.Frame().after(100) # 稍微減緩循環

        threading.Thread(target=wait_for_ctrl, daemon=True).start()

    def _select_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            self.file_path = path
            self.lbl_file_path.configure(text=os.path.basename(path), text_color="white")
            self._log(f"已選取檔案: {path}")

    def _process_html_report(self):
        if not self.engine_ready:
            messagebox.showwarning("警告", "引擎尚未就緒，請稍候。")
            return
            
        path = filedialog.askopenfilename(title="選取原始 HTML 報表", 
                                         filetypes=[("HTML files", "*.html;*.htm"), ("All files", "*.*")],
                                         initialdir=r"\\1002vpn2-pc\1002vpn-2(C)")
        if not path:
            return
            
        self._log(f"開始處理報表: {path}")
        output_name = "serial_list.txt"
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_name)
        
        success = self.engine.process_report_html(path, output_path, self._log)
        
        if success:
            self.file_path = output_path
            full_path = os.path.abspath(output_path)
            self.lbl_file_path.configure(text="serial_list.txt", text_color="#2ECC71")
            self._log(f"成功產出序號檔！檔案位置：")
            self._log(f"{full_path}")
            messagebox.showinfo("成功", f"序號整理完成！\n檔案已儲存至：\n{full_path}")
        else:
            messagebox.showerror("失敗", "報表處理失敗，請檢查檔案格式或內容。")

    def _log(self, message):
        self.textbox.insert("end", f"> {message}\n")
        self.textbox.see("end")

    def _start_automation(self):
        passed_path = self.file_path
        
        # 檢查是否有未完成的任務
        if os.path.exists(self.engine.task_file):
            if messagebox.askyesno("繼續任務？", "偵測到上次未完成的進度，是否要繼續執行？\n點擊「否」則會讀取新選取的檔案。"):
                passed_path = None # 讓引擎讀取 task_file
            else:
                if not self.file_path:
                    messagebox.showwarning("警告", "請選取新的序號文件！")
                    return
        elif not self.file_path:
            messagebox.showwarning("警告", "請先選取序號文件！")
            return

        if self.engine.is_running:
            return

        self._log("自動化流程啟動...")
        self.btn_start.configure(state="disabled")
        
        thread = threading.Thread(target=self.engine.process_document, 
                                  args=(passed_path, self._log), daemon=True)
        thread.start()
        self._monitor_thread(thread)

    def _monitor_thread(self, thread):
        if thread.is_alive():
            self.after(500, lambda: self._monitor_thread(thread))
        else:
            self.btn_start.configure(state="normal")
            self._log("任務結束。")

    def _stop_automation(self):
        self.engine.stop()
        self._log("正在停止...")

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if __name__ == "__main__":
    logging.info(f"進入主進入點. 系統路徑: {sys.executable}")
    if is_admin():
        logging.info("已取得管理員權限，啟動主視窗...")
        try:
            app = PharmacyApp()
            app.mainloop()
        except Exception as e:
            logging.error(f"應用程式執行崩潰: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            input("\n[嚴重錯誤] 應用程式崩潰，請拍下這個畫面並按 Enter 離開...")
    else:
        # 重新以管理員身分執行，並維持目前的執行目錄
        logging.info("未取得管理員權限，嘗試重新提權啟動...")
        script_path = os.path.abspath(__file__)
        work_dir = os.path.dirname(script_path)
        # 用雙引號包好路徑以防空白或括號造成解析失敗
        params = f'"{script_path}"'
        python_exe = f'"{sys.executable}"'
        try:
            # 這裡我們不包 python_exe 的引號在 ShellExecuteW 的第三個參數中，
            # 因為 ShellExecuteW 自己會處理執行檔路徑，但在某些情況下傳引號反而會錯。
            # 直接使用原生的 sys.executable，但加強錯誤捕捉。
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, work_dir, 1)
        except Exception as e:
            logging.error(f"提權啟動失敗: {e}", exc_info=True)
            input(f"提權啟動失敗: {e}\n請按 Enter 鍵離開...")
